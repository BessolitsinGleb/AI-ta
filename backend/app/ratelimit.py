"""Лимит запросов против спама и перебора: счётчики в Redis (общие для всех воркеров), без Redis — в памяти."""
from __future__ import annotations

from fastapi import HTTPException, Request

from .store import store


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def check(key: str, limit: int, window_s: int) -> None:
    count, retry = store.hit(f"rl:{key}:{window_s}", window_s)
    if count > limit:
        raise HTTPException(429, "Слишком много запросов. Попробуйте чуть позже.", headers={"Retry-After": str(retry)})


def reset() -> None:
    store.flush()
