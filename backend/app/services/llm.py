"""LLM 适配器（OpenAI 兼容接口）：DeepSeek / Kimi 可插拔（R-023）。

DeepSeek 与 Kimi 均为 OpenAI 兼容 API；统一实现，
密钥/地址/模型名全部走 .env（ECHO_DEEPSEEK_* / ECHO_KIMI_*）。
"""

from __future__ import annotations

import json
import re

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
    pass


class OpenAIClient:
    """OpenAI 兼容客户端（chat completions）。"""

    def __init__(self, base_url: str, api_key: str, model: str, supports_temperature: bool = True):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        # 推理模型（如 kimi-k3）只允许 temperature=1 → 不传该参数
        self.supports_temperature = supports_temperature

    def _post(self, payload: dict) -> dict:
        if not self.api_key:
            raise LLMError("未配置 API Key")
        with httpx.Client(timeout=180) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]

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
        return (message.get("content") or "").strip()

    def _chat_json(self, messages: list[dict], temperature: float, max_tokens: int) -> dict:
        payload = {"model": self.model, "messages": messages, "max_tokens": max_tokens}
        if self.supports_temperature:
            payload["temperature"] = temperature
            payload["response_format"] = {"type": "json_object"}
        return self._post(payload)

    def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> dict:
        message = self._chat_json(messages, temperature, max_tokens)
        raw = (message.get("content") or "").strip()
        if not raw:
            raw = (message.get("reasoning_content") or "").strip()
        result = _parse_json(raw)
        if not isinstance(result, dict):
            raise LLMError("模型未返回合法 JSON")
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
