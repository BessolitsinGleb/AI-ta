"""Адреса точек плана: обратное геокодирование Photon (данные OSM). Считается на сервере после плана — LLM-токены не тратятся."""
from __future__ import annotations

import asyncio

from .http import cached_json
from .tools.base import ToolContext

PHOTON = "https://photon.komoot.io/reverse"
PARALLEL = 4  # вежливо к общему сервису: не больше четырёх запросов разом


def format_address(p: dict) -> str:
    """«Светланская улица, 1, Владивосток»; за городом — посёлок или район."""
    parts = []
    if p.get("street"):
        parts.append(f"{p['street']}, {p['housenumber']}" if p.get("housenumber") else p["street"])
    place = p.get("city") or p.get("town") or p.get("village") or p.get("locality") or p.get("district") or p.get("county")
    if place and place not in parts and place != p.get("street"):
        parts.append(place)
    return ", ".join(parts)


async def reverse(lat: float, lon: float) -> str:
    data = await cached_json("GET", PHOTON, params={"lat": f"{lat:.5f}", "lon": f"{lon:.5f}", "limit": 1},
                             ttl=7 * 86400, timeout=4)
    features = data.get("features") or []
    return format_address(features[0].get("properties") or {}) if features else ""


async def add_addresses(plan: dict, ctx: ToolContext) -> None:
    """Дописывает address точкам и ночёвкам с координатами. Сервис не ответил — точка просто без адреса."""
    if ctx.offline:
        return
    spots = [it for day in plan.get("days") or [] for it in [*(day.get("items") or []), day.get("lodging") or {}]
             if it.get("type") != "transfer" and not it.get("address")]

    sem = asyncio.Semaphore(PARALLEL)

    async def one(it: dict) -> None:
        try:
            async with sem:
                addr = await reverse(float(it["lat"]), float(it["lon"]))
        except Exception:  # нет координат, таймаут, сервис недоступен
            return
        if addr:
            it["address"] = addr

    await asyncio.gather(*(one(it) for it in spots))
    if any(it.get("address") for it in spots):
        ctx.sources.add("Photon (адреса, OpenStreetMap)")
