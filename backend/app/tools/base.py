"""Базовые типы тулов: описание для LLM + обработчик + компактный вывод для сжатия контекста."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Awaitable, Callable

from ..config import DATA_DIR


@dataclass
class ToolContext:
    """Состояние одного запуска агента, общее для всех вызовов тулов."""

    today: date
    compact: bool = True  # сжатие контекста: в LLM уходит только существенное
    offline: bool = False
    routes: dict[str, dict] = field(default_factory=dict)  # route_id -> геометрия и метаданные
    weather: dict[str, dict] = field(default_factory=dict)  # "lat,lon" -> прогноз по дням
    fuel: dict[str, dict] = field(default_factory=dict)  # route_id -> результат поиска АЗС
    transport_trips: dict[str, dict] = field(default_factory=dict)  # trip_id -> рейс
    places_seen: dict[str, dict] = field(default_factory=dict)
    sources: set[str] = field(default_factory=set)  # какие реальные/офлайн источники использованы


Handler = Callable[[dict, ToolContext], Awaitable[dict]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Handler
    compactor: Callable[[dict], dict] | None = None

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }

    async def run(self, args: dict, ctx: ToolContext) -> tuple[dict, dict]:
        """Возвращает (полный результат, то, что увидит LLM)."""
        full = await self.handler(args, ctx)
        visible = self.compactor(full) if (ctx.compact and self.compactor) else full
        return full, visible


_data_cache: dict[str, Any] = {}


def load_data(name: str) -> Any:
    if name not in _data_cache:
        _data_cache[name] = json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
    return _data_cache[name]


def stable_hash(*parts: object) -> int:
    """Детерминированный хэш (в отличие от hash()) — для воспроизводимых моков."""
    h = 2166136261
    for ch in "|".join(map(str, parts)):
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h


def parse_date(value: str | None, default: date) -> date:
    if not value:
        return default
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return default


WEEKDAYS_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
