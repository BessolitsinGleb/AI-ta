"""Клиент OpenRouter (OpenAI-совместимый chat/completions с tool calling) + учёт токенов и стоимости."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .config import settings


class LLMError(RuntimeError):
    pass


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0
    latency_s: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, raw: dict | None, latency: float) -> None:
        raw = raw or {}
        self.prompt_tokens += int(raw.get("prompt_tokens") or 0)
        self.completion_tokens += int(raw.get("completion_tokens") or 0)
        self.cost_usd += float(raw.get("cost") or 0.0)
        self.calls += 1
        self.latency_s += latency

    def dict(self) -> dict:
        return {"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens, "cost_usd": round(self.cost_usd, 6), "llm_calls": self.calls,
                "llm_latency_s": round(self.latency_s, 2)}


@dataclass
class LLMResponse:
    message: dict
    usage: dict = field(default_factory=dict)
    model: str = ""


class ChatModel(Protocol):
    model: str

    async def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse: ...


class OpenRouterLLM:
    def __init__(self, model: str, api_key: str | None = None, temperature: float = 0.2):
        self.model = model
        self.api_key = api_key if api_key is not None else settings.openrouter_api_key
        self.temperature = temperature
        if not self.api_key:
            raise LLMError("OPENROUTER_API_KEY не задан — добавьте ключ в .env")

    async def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": self.temperature,
            "max_tokens": settings.llm_max_tokens,  # без лимита OpenRouter резервирует кредиты под 64k токенов ответа
            "usage": {"include": True},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/amba-travel-agent",
            "X-Title": "Amba Travel Agent (Primorye)",
        }
        last_err: Exception | None = None
        async with httpx.AsyncClient(timeout=settings.llm_timeout_s) as client:
            for attempt in range(4):
                try:
                    resp = await client.post(f"{settings.openrouter_base_url}/chat/completions", json=body, headers=headers)
                    if resp.status_code in (429, 500, 502, 503, 504):
                        raise LLMError(f"OpenRouter {resp.status_code}: {resp.text[:200]}")
                    if resp.status_code >= 400:
                        raise LLMError(f"OpenRouter {resp.status_code}: {resp.text[:300]}")
                    data = resp.json()
                    if data.get("error"):
                        raise LLMError(f"OpenRouter: {json.dumps(data['error'], ensure_ascii=False)[:300]}")
                    choice = (data.get("choices") or [{}])[0]
                    msg = choice.get("message") or {}
                    return LLMResponse(message=msg, usage=data.get("usage") or {}, model=data.get("model", self.model))
                except (httpx.HTTPError, LLMError) as exc:
                    last_err = exc
                    if isinstance(exc, LLMError) and "OpenRouter 4" in str(exc) and "429" not in str(exc):
                        break  # 400/401/402/403 — повторять бессмысленно
                    # бесплатные модели часто отвечают 429 — ждём дольше
                    await asyncio.sleep((6 if "429" in str(exc) else 1.5) * (attempt + 1))
        raise LLMError(str(last_err))


def timed() -> float:
    return time.perf_counter()
