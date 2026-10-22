"""Адреса точек плана: обратное геокодирование по данным OSM. Считается на сервере после плана — LLM-токены не тратятся.

Основной сервис — Photon (быстрый, без жёсткого лимита). Если он лежит, берём Nominatim (не чаще раза в секунду).
"""
from __future__ import annotations

import asyncio
import time

from .http import cached_json
from .tools.base import ToolContext
from .tools.geocode import nominatim_turn

PHOTON = "https://photon.komoot.io/reverse"
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
PARALLEL = 4  # вежливо к общему сервису: не больше четырёх запросов разом
_photon_down_until = 0.0  # Photon не ответил — 10 минут его не ждём


def format_address(p: dict) -> str:
    """«Светланская улица, 1, Владивосток»; за городом — посёлок или район."""
    parts = []
    if p.get("street"):
        parts.append(f"{p['street']}, {p['housenumber']}" if p.get("housenumber") else p["street"])
    place = p.get("city") or p.get("town") or p.get("village") or p.get("locality") or p.get("district") or p.get("county")
    if place and place not in parts and place != p.get("street"):
        parts.append(place)
    return ", ".join(parts)


def from_nominatim(a: dict) -> dict:
    """Поля адреса Nominatim → те же, что у Photon."""
    return {"street": a.get("road") or a.get("pedestrian"), "housenumber": a.get("house_number"),
            "city": a.get("city"), "town": a.get("town"), "village": a.get("village") or a.get("hamlet"),
            "district": a.get("suburb"), "county": a.get("county")}


async def reverse(lat: float, lon: float) -> str:
    global _photon_down_until
    if time.time() > _photon_down_until:
        try:
            data = await cached_json("GET", PHOTON, params={"lat": f"{lat:.5f}", "lon": f"{lon:.5f}", "limit": 1},
                                     ttl=7 * 86400, timeout=4)
            features = data.get("features") or []
            return format_address(features[0].get("properties") or {}) if features else ""
        except Exception:  # таймаут, 5xx — переключаемся на запасной сервис
            _photon_down_until = time.time() + 600
    await nominatim_turn()
    data = await cached_json("GET", NOMINATIM, params={"lat": f"{lat:.5f}", "lon": f"{lon:.5f}", "format": "jsonv2",
                                                       "zoom": 18, "accept-language": "ru"}, ttl=7 * 86400, timeout=5)
    return format_address(from_nominatim(data.get("address") or {}))


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
        ctx.sources.add("адреса: OpenStreetMap (Photon / Nominatim)")
