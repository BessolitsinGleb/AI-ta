"""Быстрое хранилище: Redis (лимиты запросов, история диалогов). Без Redis — память процесса, приложение не падает."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger("amba.store")
PREFIX = "amba:"


class MemoryStore:
    kind = "memory"

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def _alive(self, key: str):
        item = self._data.get(key)
        if item and item[0] < time.time():
            self._data.pop(key, None)
            return None
        return item

    def hit(self, key: str, window_s: int) -> tuple[int, int]:
        """Счётчик в фиксированном окне: (сколько уже было, секунд до сброса)."""
        with self._lock:
            item = self._alive(key)
            count, expires = (item[1] + 1, item[0]) if item else (1, time.time() + window_s)
            self._data[key] = (expires, count)
            return count, max(1, int(expires - time.time()))

    def get_json(self, key: str) -> Any:
        with self._lock:
            item = self._alive(key)
        return json.loads(item[1]) if item else None

    def set_json(self, key: str, value: Any, ttl_s: int) -> None:
        with self._lock:
            self._data[key] = (time.time() + ttl_s, json.dumps(value, ensure_ascii=False, default=str))

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def ping(self) -> bool:
        return True

    def flush(self) -> None:
        with self._lock:
            self._data.clear()


class RedisStore:
    kind = "redis"

    def __init__(self, client) -> None:
        self.r = client
        self.fallback = MemoryStore()  # если Redis моргнул — работаем на памяти, а не отдаём 500
        self._warned = False

    def _safe(self, fn, fallback_fn):
        import redis

        try:
            return fn()
        except redis.RedisError as exc:
            if not self._warned:
                log.warning("Redis недоступен (%s) — временно храню в памяти процесса", exc)
                self._warned = True
            return fallback_fn()

    def hit(self, key: str, window_s: int) -> tuple[int, int]:
        def go():
            pipe = self.r.pipeline()
            pipe.incr(PREFIX + key)
            pipe.expire(PREFIX + key, window_s, nx=True)  # окно стартует с первого запроса
            pipe.ttl(PREFIX + key)
            count, _, ttl = pipe.execute()
            return int(count), max(1, int(ttl))
        return self._safe(go, lambda: self.fallback.hit(key, window_s))

    def get_json(self, key: str) -> Any:
        def go():
            raw = self.r.get(PREFIX + key)
            return json.loads(raw) if raw else None
        return self._safe(go, lambda: self.fallback.get_json(key))

    def set_json(self, key: str, value: Any, ttl_s: int) -> None:
        payload = json.dumps(value, ensure_ascii=False, default=str)
        self._safe(lambda: self.r.set(PREFIX + key, payload, ex=ttl_s), lambda: self.fallback.set_json(key, value, ttl_s))

    def delete(self, key: str) -> None:
        self._safe(lambda: self.r.delete(PREFIX + key), lambda: self.fallback.delete(key))

    def ping(self) -> bool:
        return bool(self._safe(lambda: self.r.ping(), lambda: False))

    def flush(self) -> None:
        def go():
            for k in self.r.scan_iter(PREFIX + "*"):
                self.r.delete(k)
        self._safe(go, lambda: None)
        self.fallback.flush()


def _make():
    url = os.getenv("REDIS_URL", "")
    if not url:
        return MemoryStore()
    import redis

    client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=0.5, socket_connect_timeout=0.5)
    return RedisStore(client)


store = _make()
