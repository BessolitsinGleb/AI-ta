"""Скриптованная LLM для тестов агентного цикла."""
from __future__ import annotations

import json

from app.llm import LLMResponse


def call(name: str, args: dict, idx: int = 0) -> dict:
    return {"id": f"c_{name}_{idx}", "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


class ScriptedLLM:
    """Отдаёт заранее заданные ответы по очереди и запоминает, что ей прислали."""

    model = "test/scripted"

    def __init__(self, steps: list):
        self.steps = list(steps)
        self.seen: list[list[dict]] = []

    async def chat(self, messages, tools):
        self.seen.append([dict(m) for m in messages])
        step = self.steps.pop(0)
        if callable(step):
            step = step(messages)
        if isinstance(step, str):
            msg = {"role": "assistant", "content": step}
        else:
            msg = {"role": "assistant", "content": "", "tool_calls": step}
        return LLMResponse(msg, {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "cost": 0.0001}, self.model)


class ExplodingLLM:
    model = "test/exploding"

    async def chat(self, messages, tools):  # pragma: no cover — не должна вызываться
        raise AssertionError("LLM не должна вызываться")
