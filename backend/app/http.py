"""Общий HTTP-клиент с простым TTL-кэшем — чтобы не долбить открытые API одинаковыми запросами."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from .config import settings

_cache: dict[str, tuple[float, Any]] = {}
_locks: dict[str, asyncio.Lock] = {}
_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=settings.http_timeout_s,
            headers={"User-Agent": settings.user_agent, "Accept-Language": "ru"},
            follow_redirects=True,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def clear_cache() -> None:
    _cache.clear()


async def cached_json(
    method: str,
    url: str,
    *,
    params: dict | None = None,
    data: dict | None = None,
    ttl: float = 1800,
    timeout: float | None = None,
) -> Any:
    key = json.dumps([method, url, params, data], sort_keys=True, ensure_ascii=False)
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.time():
            return hit[1]
        client = get_client()
        resp = await client.request(method, url, params=params, data=data, timeout=timeout or settings.http_timeout_s)
        resp.raise_for_status()
        payload = resp.json()
        _cache[key] = (time.time() + ttl, payload)
        return payload
