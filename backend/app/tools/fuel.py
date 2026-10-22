"""АЗС по маршруту из OpenStreetMap: виды топлива, бренд, часы и услуги — из тегов OSM (у части станций они не заполнены).

Берём снимок всех АЗС края (data/fuel_osm.json, обновляет scripts/update_fuel.py): Overpass отвечает слишком долго.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..geo import haversine_km
from .base import Tool, ToolContext, load_data


OVERPASS = "https://overpass-api.de/api/interpreter"
SNAPSHOT = Path(__file__).resolve().parents[1] / "data" / "fuel_osm.json"
NEAR_ROUTE_KM = 6.0
FUELS = ["АИ-92", "АИ-95", "ДТ"]
OSM_FUEL = {"АИ-92": "fuel:octane_92", "АИ-95": "fuel:octane_95", "ДТ": "fuel:diesel", "АИ-98": "fuel:octane_98", "Газ": "fuel:lpg"}
SERVICES = {"shop": "магазин", "toilets": "туалет", "car_wash": "мойка", "compressed_air": "подкачка шин",
            "self_service": "самообслуживание"}
NOTE = "виды топлива, часы и услуги — из OpenStreetMap; остатки топлива сети в открытом доступе не публикуют"


def fuel_types(tags: dict) -> dict[str, bool | None]:
    """АИ-92/95/ДТ: True — продаёт, False — нет, None — в OSM не указано. АИ-98 и газ — только если есть."""
    out: dict[str, bool | None] = {}
    for name, key in OSM_FUEL.items():
        val = tags.get(key)
        if name in FUELS:
            out[name] = True if val == "yes" else False if val == "no" else None
        elif val == "yes":
            out[name] = True
    return out


def station_info(el: dict) -> dict:
    t = el.get("tags", {})
    pos = el if "lat" in el else el.get("center", {})  # АЗС-контур (way) — по центру
    hours = t.get("opening_hours")
    services = [ru for key, ru in SERVICES.items() if t.get(key) not in (None, "no")]
    if any(t.get(k) == "yes" for k in ("payment:cards", "payment:credit_cards", "payment:debit_cards", "payment:visa", "payment:mir")):
        services.append("оплата картой")
    street = " ".join(x for x in (t.get("addr:street"), t.get("addr:housenumber")) if x)
    return {"id": f"osm{el['id']}", "name": t.get("name") or t.get("brand") or "АЗС", "lat": pos["lat"], "lon": pos["lon"],
            "brand": t.get("brand") or t.get("operator"), "fuel": fuel_types(t),
            "hours": "круглосуточно" if hours == "24/7" else hours, "services": services,
            "address": ", ".join(x for x in (street, t.get("addr:city")) if x) or None}


def _project(geometry: list[list[float]], lat: float, lon: float) -> tuple[float, float]:
    """(расстояние от маршрута, км от старта) — по ближайшей вершине упрощённой геометрии."""
    best, best_i = 1e9, 0
    for i, (glat, glon) in enumerate(geometry):
        d = haversine_km(lat, lon, glat, glon)
        if d < best:
            best, best_i = d, i
    along = sum(haversine_km(*geometry[i], *geometry[i + 1]) for i in range(best_i))
    return best, along


@lru_cache(maxsize=1)
def _snapshot() -> dict:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8")) if SNAPSHOT.exists() else {}


async def find_fuel_stations(args: dict, ctx: ToolContext) -> dict:
    route = ctx.routes.get(str(args.get("route_id", "")))
    if not route:
        return {"error": "неизвестный route_id — сначала вызови build_route"}
    day = str(args.get("date") or ctx.today.isoformat())
    fuel = str(args.get("fuel") or "АИ-95")
    geom = route["geometry"]
    s = min(p[0] for p in geom) - 0.05
    n = max(p[0] for p in geom) + 0.05
    w = min(p[1] for p in geom) - 0.05
    e = max(p[1] for p in geom) + 0.05

    snap = _snapshot()
    stations, source = [st for st in snap.get("stations", []) if s <= st["lat"] <= n and w <= st["lon"] <= e], "osm"
    if snap:
        ctx.sources.add(f"OpenStreetMap: АЗС (снимок {str(snap.get('osm_timestamp') or '')[:10]})")
    else:  # снимка нет — короткий список из датасета
        stations, source = load_data("fuel_offline.json"), "offline"
        ctx.sources.add("офлайн-список АЗС")

    on_route = []
    for st in stations:
        dist, along = _project(geom, st["lat"], st["lon"])
        if dist <= NEAR_ROUTE_KM:
            on_route.append({**st, "fuel": st.get("fuel") or {f: None for f in FUELS}, "services": st.get("services") or [],
                             "km_from_start": round(along, 1), "off_route_km": round(dist, 1)})
    on_route.sort(key=lambda x: x["km_from_start"])
    # Отбрасываем дубли (несколько колонок одной АЗС).
    dedup = []
    for st in on_route:
        if not dedup or abs(st["km_from_start"] - dedup[-1]["km_from_start"]) > 1.0:
            dedup.append(st)
    # «Нет данных» не считаем отказом: перегон считаем по станциям, где топливо не отмечено как отсутствующее
    with_fuel = [st for st in dedup if st["fuel"].get(fuel) is not False]
    confirmed = sum(1 for st in dedup if st["fuel"].get(fuel) is True)
    total = route["distance_km"]
    marks = [0.0] + [st["km_from_start"] for st in with_fuel] + [total]
    max_gap = max(b - a for a, b in zip(marks, marks[1:])) if len(marks) > 1 else total
    result = {
        "route_id": route["route_id"], "fuel": fuel, "date": day, "source": source,
        "stations": dedup, "stations_with_fuel": len(with_fuel), "confirmed": confirmed, "max_gap_km": round(max_gap, 1),
        "availability_note": NOTE,
    }
    if max_gap > 200:
        result["warning"] = f"перегон {max_gap:.0f} км без {fuel} — заправьтесь заранее"
    ctx.fuel[route["route_id"]] = result
    return result


def _compact(res: dict) -> dict:
    if res.get("error"):
        return res
    fuel = res["fuel"]
    st = [{"name": s["name"][:40], "km": s["km_from_start"], "has": s["fuel"].get(fuel), "lat": round(s["lat"], 3),
           "lon": round(s["lon"], 3), **({"hours": s["hours"]} if s.get("hours") else {})} for s in res["stations"]]
    # Длинный список сокращаем: оставляем станции с топливом равномерно и все «пустые».
    if len(st) > 10:
        st = [s for s in st if s["has"] is False][:3] + [s for s in st if s["has"] is not False][:: max(1, len(st) // 7)]
        st.sort(key=lambda s: s["km"])
    out = {"fuel": fuel, "stations": st, "with_fuel": res["stations_with_fuel"], "confirmed": res.get("confirmed", 0),
           "max_gap_km": res["max_gap_km"], "note": "has=null — в OSM не указано"}
    if res.get("warning"):
        out["warning"] = res["warning"]
    return out


TOOL = Tool(
    name="find_fuel_stations",
    description=("АЗС вдоль построенного маршрута (OpenStreetMap): виды топлива, часы, услуги, перегон без топлива. "
                 "Обязателен для поездок на машине."),
    parameters={
        "type": "object",
        "properties": {
            "route_id": {"type": "string"},
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "fuel": {"type": "string", "enum": FUELS},
        },
        "required": ["route_id"],
    },
    handler=find_fuel_stations,
    compactor=_compact,
)
