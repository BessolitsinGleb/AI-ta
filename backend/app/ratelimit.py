"""Простой лимит попыток в памяти процесса: защищает вход, регистрацию и письма от перебора и спама."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_hits: dict[str, deque] = defaultdict(deque)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def check(key: str, limit: int, window_s: int) -> None:
    now = time.monotonic()
    q = _hits[key]
    while q and q[0] <= now - window_s:
        q.popleft()
    if len(q) >= limit:
        retry = int(window_s - (now - q[0])) + 1
        raise HTTPException(429, "Слишком много попыток. Попробуйте чуть позже.", headers={"Retry-After": str(retry)})
    q.append(now)


def reset() -> None:
    _hits.clear()
