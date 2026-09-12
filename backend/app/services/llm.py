"""LLM 适配器（OpenAI 兼容接口）：DeepSeek / Kimi 可插拔（R-023）。

DeepSeek 与 Kimi 均为 OpenAI 兼容 API；统一实现，
密钥/地址/模型名全部走 .env（ECHO_DEEPSEEK_* / ECHO_KIMI_*）。
"""

from __future__ import annotations

import json
import re
import time

import httpx

from ..config import get_settings




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


class OpenAIClient:
    """OpenAI 兼容客户端（chat completions）。

    调用有**硬性墙钟上限**（`timeout_seconds`，默认取 `.env` `ECHO_LLM_TIMEOUT_SECONDS`）：
    只靠 httpx 的 read timeout 不够——实测 DeepSeek 思考时偶发长时间挂起
    （一次真实调用挂了 39 分钟才超时），会让「超时降级」这条兜底形同虚设。
    所以这里用流式读取 + 每次收到数据检查墙钟，超限立即按超时失败交给上层降级（R-139）。
    """

    DEFAULT_TIMEOUT_SECONDS = 600
    # 单次「无数据到达」上限：必须大于推理模型最长静默思考时间（实测 Kimi 会静默 >30s）
    READ_TIMEOUT_SECONDS = 180.0

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
        # read：多久没有任何数据到达就认为是死连接。推理模型「思考中」可能长时间不吐字节
        # （实测 Kimi 用 read=30 会稳定超时，40s 就被判死），所以给足 180s；
        # 「连接一直有字节但永远不结束」由上面的墙钟 deadline 兜底（实测曾挂 39 分钟）。
        timeout = httpx.Timeout(connect=15.0, read=self.READ_TIMEOUT_SECONDS, write=60.0, pool=30.0)
        try:
            with httpx.Client(timeout=timeout) as client:
                with client.stream("POST", url, headers=headers, json=payload) as resp:
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


class DeepSeekClient(OpenAIClient):
    def __init__(self, settings=None):
        s = settings or get_settings()
        super().__init__(s.deepseek_base_url, s.deepseek_api_key, s.deepseek_model)


class KimiClient(OpenAIClient):
    def __init__(self, settings=None):
        s = settings or get_settings()
        # kimi 推理模型只接受 temperature=1 → 不传 temperature
        super().__init__(s.kimi_base_url, s.kimi_api_key, s.kimi_model, supports_temperature=False)


def get_llm(name: str, settings=None):
    """按名字取客户端：deepseek | kimi。"""
    name = (name or "").lower()
    if name == "kimi":
        return KimiClient(settings)
    return DeepSeekClient(settings)
