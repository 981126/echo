"""LLM 适配器（OpenAI 兼容接口）：DeepSeek / Kimi 可插拔（R-023）。

DeepSeek 与 Kimi 均为 OpenAI 兼容 API；统一实现，
密钥/地址/模型名全部走 .env（ECHO_DEEPSEEK_* / ECHO_KIMI_*）。
"""

from __future__ import annotations

import atexit
import json
import re
import threading
import time

import httpx

from ..config import get_settings
from ..core.log import get_logger

log = get_logger("llm")




def _parse_json(raw: str):
    """解析 JSON：先整体解析；再去代码围栏；再扫描第一个合法 JSON 对象。

    兼容推理模型输出（前后有推理文字、markdown 代码块、尾注等）。
    """
    text = (raw or "").strip()
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = decoder.raw_decode(text[i:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
    return None


class LLMError(RuntimeError):
    """LLM 不可用（未配置 Key、网络/HTTP 失败等）或输出不可用。"""


class LLMUnusableOutput(LLMError):
    """拿到了响应但输出不可用（空正文 / 思考吃光预算 / 非法 JSON）。

    这类失败**值得抬预算或重试**（推理模型的思考长度有随机性），所以与"服务不可用"区分开：
    `llm_router` 会先翻倍 max_tokens 重试，再降级到另一个模型（R-139）。
    """


def _content_or_reason(message: dict) -> str:
    """取正文；正文为空但模型写了思考内容时，给出可读原因（R-139）。

    DeepSeek V4.1 Flash 与 Kimi 都是**推理模型**：`max_tokens` 同时包含思考与正文，
    预算不够时会 `finish_reason=length` 且 `content` 为空、`reasoning_content` 却很长。
    这会让上层误以为是「服务挂了」，所以这里明确抛出可读错误，交由 `llm_router` 抬高预算重试/降级。
    """
    content = (message.get("content") or "").strip()
    if content:
        return content
    reasoning = (message.get("reasoning_content") or "").strip()
    if reasoning:
        raise LLMUnusableOutput(
            f"推理预算被思考吃光（思考 {len(reasoning)} 字、正文为空），需要更大的 max_tokens"
        )
    if message.get("tool_calls"):
        return ""  # AI 对话的工具调用轮：正文可以为空
    return ""


# ---------- R-240 S4：模块级 HTTP 客户端复用 ----------

# 背景（.tmp/audit/infra.md F-01）：原来每次调用都 `with httpx.Client(...)` 新建 → 新连接池、
# 重新 TCP+TLS 握手（一次 100~300ms）；一篇稿典型 12~13 次调用 → 白扔 1.3~3.9s，还放大系统代理抖动。
# httpx.Client 官方明确线程安全（可跨线程共享连接池），同仓库 `platform/tikhub.py` 已有复用先例。
# 单次调用的墙钟预算改为每请求传 `timeout=`（见 `_post`），因此池自身 `timeout=None`；
# `keepalive_expiry` 必须显式给大值（httpx 默认 5s，讨论轮间隔 3~10s 会让连接复用失效）——
# 它是 `Limits` 的参数，不是 Client 的。
_LIMITS = httpx.Limits(
    max_connections=8,
    max_keepalive_connections=4,
    keepalive_expiry=120.0,
)
_CLIENTS: dict[tuple[str, type], httpx.Client] = {}
_CLIENTS_LOCK = threading.Lock()


def _client_for(base_url: str) -> httpx.Client:
    """按 base_url 取共享 Client（懒创建 + 双检锁）。

    key 里带上当前 `httpx.Client` 类对象：生产环境恒为同一个类，等价于「只按 base_url 缓存」；
    测试里 monkeypatch `httpx.Client` 后自然与上一用例的假客户端隔离，不会跨用例复用假连接。
    """
    key = (base_url or "", httpx.Client)
    client = _CLIENTS.get(key)
    if client is not None:
        return client
    with _CLIENTS_LOCK:
        client = _CLIENTS.get(key)
        if client is None:
            client = httpx.Client(
                timeout=None,
                limits=_LIMITS,
                trust_env=True,
            )
            _CLIENTS[key] = client
    return client


def close_all_clients() -> None:
    """关闭并清空共享 Client（进程退出 atexit 自动调用；测试可主动重置）。"""
    with _CLIENTS_LOCK:
        clients = list(_CLIENTS.values())
        _CLIENTS.clear()
    for client in clients:
        try:
            client.close()
        except Exception:  # noqa: BLE001 退出阶段关不掉也不该再抛
            pass


atexit.register(close_all_clients)


class OpenAIClient:
    """OpenAI 兼容客户端（chat completions）。

    调用有**硬性墙钟上限**（`timeout_seconds`，默认取 `.env` `ECHO_LLM_TIMEOUT_SECONDS` = 600s）：
    - 请求没设 `stream`，所以服务端要等生成完才吐字节 → `read` 超时实际就是「这次调用必须在这个时间内完成」；
      推理模型的思考时间随预算增长（实测 Kimi 拉到 12000 预算时会跑到 180s 以上），
      所以 `read` 与墙钟取同一个值，单一语义：**单次调用最多 `timeout_seconds` 秒**。
    - 只靠 httpx 的 read timeout 也不够：实测 DeepSeek 思考时偶发「一直有零碎字节但永不结束」，
      一次真实调用挂了 39 分钟。因此流式读取时逐块检查墙钟，超限立即按超时失败交给上层降级（R-139/R-142）。
    """

    DEFAULT_TIMEOUT_SECONDS = 600

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        supports_temperature: bool = True,
        timeout_seconds: int | None = None,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        # 推理模型（如 kimi-k2.6）只允许 temperature=1 → 不传该参数
        self.supports_temperature = supports_temperature
        if timeout_seconds is None:
            timeout_seconds = int(getattr(get_settings(), "llm_timeout_seconds", 0) or 0) or self.DEFAULT_TIMEOUT_SECONDS
        self.timeout_seconds = max(30, int(timeout_seconds))

    def _post(self, payload: dict) -> dict:
        if not self.api_key:
            raise LLMError("未配置 API Key")
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        deadline = time.monotonic() + self.timeout_seconds
        # read 与墙钟同值（见类注释）：不设 stream 时它等价于「单次调用总时限」。
        # connect 单独给短值，连不上时快速失败。
        # R-240 S4：共享 Client 自身 timeout=None，这里每个请求显式传 timeout，语义与原来「每次新建」一致。
        timeout = httpx.Timeout(connect=15.0, read=float(self.timeout_seconds), write=60.0, pool=30.0)
        fallback_client: httpx.Client | None = None
        try:
            try:
                client = _client_for(self.base_url)
            except Exception:  # noqa: BLE001 共享池建不起来 → 回退旧行为（每次新建、用完关闭）
                log.exception("共享 LLM 客户端创建失败，回退每次新建（base_url=%s）", self.base_url)
                fallback_client = httpx.Client(timeout=timeout)
                client = fallback_client
            try:
                with client.stream(
                    "POST", url, headers=headers, json=payload, timeout=timeout
                ) as resp:
                    if resp.status_code >= 400:
                        resp.read()
                        raise LLMError(f"HTTP {resp.status_code}：{(resp.text or '')[:200]}")
                    chunks: list[bytes] = []
                    # 注意用 iter_bytes 而不是 iter_raw：iter_raw 给的是「未解码」字节，
                    # Kimi 的响应是 gzip 压缩的，用 iter_raw 会得到压缩字节并解析失败（R-139 实测踩到）。
                    for chunk in resp.iter_bytes():
                        chunks.append(chunk)
                        if time.monotonic() > deadline:
                            raise LLMError(
                                f"调用超过 {self.timeout_seconds}s 仍未返回（模型：{self.model}），按超时处理"
                            )
            except httpx.TimeoutException as exc:
                raise LLMError(f"调用超时（模型：{self.model}）：{type(exc).__name__}") from exc
        finally:
            if fallback_client is not None:
                fallback_client.close()
        if time.monotonic() > deadline:
            raise LLMError(f"调用超过 {self.timeout_seconds}s 仍未返回（模型：{self.model}），按超时处理")
        try:
            data = json.loads(b"".join(chunks).decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise LLMUnusableOutput(f"响应不是合法 JSON（模型：{self.model}）：{exc}") from exc
        try:
            return data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnusableOutput(f"响应缺少 choices[0].message（模型：{self.model}）：{str(data)[:200]}") from exc

    def chat_completion(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        tools: list[dict] | None = None,
    ) -> dict:
        payload = {"model": self.model, "messages": messages, "max_tokens": max_tokens}
        if self.supports_temperature:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = tools
        return self._post(payload)

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        json_mode: bool = False,
    ) -> str:
        if json_mode:
            message = self._chat_json(messages, temperature, max_tokens)
        else:
            message = self.chat_completion(messages, temperature=temperature, max_tokens=max_tokens)
        return _content_or_reason(message)

    def _chat_json(self, messages: list[dict], temperature: float, max_tokens: int) -> dict:
        payload = {"model": self.model, "messages": messages, "max_tokens": max_tokens}
        if self.supports_temperature:
            payload["temperature"] = temperature
            payload["response_format"] = {"type": "json_object"}
        return self._post(payload)

    def _json_message(self, messages: list[dict], temperature: float, max_tokens: int) -> dict:
        """JSON 调用的原始 message（带推理预算耗尽的明确报错，R-139）。"""
        message = self._chat_json(messages, temperature, max_tokens)
        _content_or_reason(message)  # 空正文 + 有思考 → 抛出可读原因，而不是「未返回合法 JSON」
        return message

    def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> dict:
        message = self._json_message(messages, temperature, max_tokens)
        raw = (message.get("content") or "").strip()
        result = _parse_json(raw)
        if not isinstance(result, dict):
            raise LLMUnusableOutput("模型未返回合法 JSON")
        return result
