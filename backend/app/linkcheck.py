"""Живы ли ссылки: сайт кафе, который не открывается, — признак, что заведение закрылось (OSM обновляется не сразу)."""
from __future__ import annotations

import asyncio
import time

import httpx

from .http import get_client

TTL_S = 12 * 3600
_seen: dict[str, tuple[float, bool | None]] = {}


async def alive(url: str, timeout: float = 5.0) -> bool | None:
    """True — открывается; False — домена нет, соединение отклонено или 404/410; None — не понять (403, 429, 5xx, таймаут)."""
    hit = _seen.get(url)
    if hit and hit[0] > time.time():
        return hit[1]
    try:
        async with get_client().stream("GET", url, timeout=timeout) as resp:  # тело не качаем — хватает статуса
            code = resp.status_code
        verdict = True if code < 400 else False if code in (404, 410) else None
    except (httpx.ConnectError, httpx.UnsupportedProtocol, httpx.InvalidURL):
        verdict = False  # DNS не знает домен или сервер не принимает соединения
    except httpx.HTTPError:
        verdict = None  # таймаут и прочее — сайт мог просто притормозить
    _seen[url] = (time.time() + TTL_S, verdict)
    return verdict


async def check_many(urls: list[str], parallel: int = 6) -> dict[str, bool | None]:
    sem = asyncio.Semaphore(parallel)

    async def one(u: str) -> tuple[str, bool | None]:
        async with sem:
            return u, await alive(u)

    return dict(await asyncio.gather(*(one(u) for u in dict.fromkeys(urls))))


async def drop_dead_links(plan: dict) -> int:
    """Убирает из плана ссылки «Сайт», которые не открываются; «На карте» — поиск Яндекса, он всегда отвечает."""
    holders = [it for day in plan.get("days") or [] for it in [*(day.get("items") or []), day.get("lodging") or {}]
               if it.get("links")]
    sites = [link["url"] for it in holders for link in it["links"] if link.get("title") == "Сайт"]
    if not sites:
        return 0
    status = await check_many(sites)
    dropped = 0
    for it in holders:
        keep = [link for link in it["links"] if link.get("title") != "Сайт" or status.get(link["url"]) is True]
        dropped += len(it["links"]) - len(keep)
        it["links"] = keep
        if it.get("url") and status.get(it["url"]) is not True:
            it.pop("url")
    return dropped
