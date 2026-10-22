"""Работает ли заведение: заходим на его сайт и читаем, что там написано.

OSM обновляется не сразу и помнит закрывшиеся кафе. Сайт выдаёт это быстрее: домена больше нет, страница 404,
домен выставлен на продажу или прямо написано «мы закрылись». Проверка не идёт во внутреннюю сеть сервера (SSRF):
ссылки приходят из OSM и от модели.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import time
from urllib.parse import urljoin, urlsplit

import httpx

from .http import get_client

TTL_S = 12 * 3600
MAX_BYTES = 150_000  # первых 150 КБ страницы хватает: главная, заголовки, баннер «мы закрылись»
MAX_REDIRECTS = 3
OPEN, CLOSED, UNKNOWN = "open", "closed", "unknown"

# Домен выставлен на продажу или отдан под заглушку регистратора — сайта у заведения больше нет
PARKED = re.compile(r"домен\s+(?:продается|продаётся|выставлен на продажу|свободен|не (?:настроен|делегирован))"
                    r"|this domain (?:is|may be) for sale|buy this domain|domain (?:is )?parked|parked domain"
                    r"|сайт (?:не опубликован|заблокирован|временно недоступен по решению)|account (?:has been )?suspended", re.I)
# Заведение само пишет, что не работает
CLOSED_TEXT = re.compile(r"(?:закрыт[аоы]?|закрылись)\s+навсегда|мы\s+закрылись|больше\s+не\s+работа(?:ем|ет)"
                         r"|прекратил[аио]?\s+(?:свою\s+)?(?:работу|деятельность)|заведение\s+закрыто"
                         r"|временно\s+не\s+работа(?:ем|ет)|(?:ресторан|кафе|бар|заведение)\s+временно\s+закрыт", re.I)

_seen: dict[str, tuple[float, str, str]] = {}


async def _resolve(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


async def _public(url: str) -> bool | None:
    """Адрес из интернета, а не внутренняя сеть сервера. None — такого домена нет (значит, и сайта нет)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.port not in (None, 80, 443):
        return False
    try:
        ip_literal = ipaddress.ip_address(parts.hostname)
    except ValueError:
        ip_literal = None
    if ip_literal is not None:
        return ip_literal.is_global
    try:
        addrs = await _resolve(parts.hostname)
    except socket.gaierror as exc:
        # «такого домена нет» — сайт мёртв; временный сбой DNS (нет сети) — не повод считать кафе закрытым
        return None if exc.errno in (socket.EAI_NONAME, getattr(socket, "EAI_NODATA", socket.EAI_NONAME)) else False
    return bool(addrs) and all(ipaddress.ip_address(a).is_global for a in addrs)


async def _fetch(url: str, timeout: float) -> tuple[str, str]:
    """Идём по редиректам сами — каждый адрес проверяем на «публичность». Тело читаем не больше MAX_BYTES."""
    for _ in range(MAX_REDIRECTS + 1):
        public = await _public(url)
        if public is None:
            return CLOSED, "домена больше нет"
        if not public:
            return UNKNOWN, "адрес не проверяем"
        async with get_client().stream("GET", url, timeout=timeout, follow_redirects=False) as resp:
            if resp.is_redirect and resp.headers.get("location"):
                url = urljoin(url, resp.headers["location"])
                continue
            if resp.status_code in (404, 410):
                return CLOSED, f"страница не найдена ({resp.status_code})"
            if resp.status_code >= 400:
                return UNKNOWN, f"сайт не дал проверить ({resp.status_code})"
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body += chunk
                if len(body) >= MAX_BYTES:
                    break
            text = body.decode(resp.encoding or "utf-8", errors="ignore")
        if m := PARKED.search(text):
            return CLOSED, "домен выставлен на продажу или отключён"
        if m := CLOSED_TEXT.search(text):
            return CLOSED, f"на сайте написано: «{m.group(0).strip()}»"
        return OPEN, "сайт работает"
    return UNKNOWN, "слишком много переадресаций"


async def site_status(url: str, timeout: float = 4.0) -> tuple[str, str]:
    """(open | closed | unknown, причина по-русски). Результат кэшируется на 12 часов."""
    hit = _seen.get(url)
    if hit and hit[0] > time.time():
        return hit[1], hit[2]
    try:
        state, why = await _fetch(url, timeout)
    except httpx.ConnectError:
        state, why = CLOSED, "сайт не отвечает"
    except (httpx.UnsupportedProtocol, httpx.InvalidURL):
        state, why = UNKNOWN, "некорректный адрес"
    except httpx.HTTPError:
        state, why = UNKNOWN, "сайт не ответил вовремя"  # мог просто притормозить — не повод считать закрытым
    _seen[url] = (time.time() + TTL_S, state, why)
    return state, why


async def alive(url: str, timeout: float = 4.0) -> bool | None:
    """True — работает, False — закрыто, None — проверить не удалось."""
    state, _ = await site_status(url, timeout)
    return {OPEN: True, CLOSED: False}.get(state)


async def check_many(urls: list[str], parallel: int = 8) -> dict[str, bool | None]:
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
    return dropped
