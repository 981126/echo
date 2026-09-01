"""DeepSeek LLM 适配器（OpenAI 兼容接口）。"""
import json

import httpx

from ..config import get_settings


class LLMError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        json_mode: bool = False,
    ) -> str:
        if not self.settings.deepseek_api_key:
            raise LLMError("未配置 ECHO_DEEPSEEK_API_KEY")
        payload = {
            "model": self.settings.deepseek_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.deepseek_api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]

    def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> dict:
        raw = self.chat(
            messages, temperature=temperature, max_tokens=max_tokens, json_mode=True
        )
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError("模型未返回合法 JSON") from exc
        if not isinstance(result, dict):
            raise LLMError("模型返回非对象 JSON")
        return result
