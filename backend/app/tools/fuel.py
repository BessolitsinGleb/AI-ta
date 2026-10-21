"""АЗС по маршруту: OSM Overpass (реальные станции) + мок наличия топлива (открытых данных нет)."""
from __future__ import annotations

from ..geo import haversine_km
from ..http import cached_json
from .base import Tool, ToolContext, load_data, stable_hash

import time

OVERPASS = "https://overpass-api.de/api/interpreter"
_overpass_down_until = 0.0  # предохранитель: Overpass часто перегружен — не ждём его на каждом запросе
NEAR_ROUTE_KM = 6.0
FUELS = ["АИ-92", "АИ-95", "ДТ"]


def availability(station_id: str, day: str) -> dict[str, bool]:
    """Мок наличия топлива: детерминирован от станции и даты; ~15% станций без АИ-95, ~7% закрыты."""
    h = stable_hash(station_id, day)
    if h % 14 == 0:
        return {f: False for f in FUELS}
    return {"АИ-92": True, "АИ-95": h % 7 != 1, "ДТ": h % 9 != 2}


def _project(geometry: list[list[float]], lat: float, lon: float) -> tuple[float, float]:
    """(расстояние от маршрута, км от старта) — по ближайшей вершине упрощённой геометрии."""
    best, best_i = 1e9, 0
    for i, (glat, glon) in enumerate(geometry):
        d = haversine_km(lat, lon, glat, glon)
        if d < best:
            best, best_i = d, i
    along = sum(haversine_km(*geometry[i], *geometry[i + 1]) for i in range(best_i))
    return best, along


async def _overpass(bbox: tuple[float, float, float, float]) -> list[dict]:
    s, w, n, e = bbox
    q = f'[out:json][timeout:8];node["amenity"="fuel"]({s},{w},{n},{e});out 200;'
    data = await cached_json("POST", OVERPASS, data={"data": q}, ttl=86400, timeout=7)
    return [{"id": f"osm{el['id']}", "name": (el.get("tags", {}).get("name") or el.get("tags", {}).get("brand") or "АЗС"),
             "lat": el["lat"], "lon": el["lon"]} for el in data.get("elements", [])]


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

    global _overpass_down_until
    stations, source = [], "offline"
    if not ctx.offline and time.time() > _overpass_down_until:
        try:
            stations = await _overpass((s, w, n, e))
            source = "overpass"
            ctx.sources.add("OSM Overpass (АЗС)")
        except Exception:
            stations = []
            _overpass_down_until = time.time() + 600
    if not stations:
        stations = load_data("fuel_offline.json")
        ctx.sources.add("офлайн-список АЗС")

    on_route = []
    for st in stations:
        dist, along = _project(geom, st["lat"], st["lon"])
        if dist <= NEAR_ROUTE_KM:
            avail = availability(st["id"], day)
            on_route.append({"id": st["id"], "name": st["name"], "lat": st["lat"], "lon": st["lon"],
                             "km_from_start": round(along, 1), "off_route_km": round(dist, 1), "fuel": avail})
    on_route.sort(key=lambda x: x["km_from_start"])
    # Отбрасываем дубли (несколько колонок одной АЗС).
    dedup = []
    for st in on_route:
        if not dedup or abs(st["km_from_start"] - dedup[-1]["km_from_start"]) > 1.0:
            dedup.append(st)
    with_fuel = [st for st in dedup if st["fuel"].get(fuel)]
    total = route["distance_km"]
    marks = [0.0] + [st["km_from_start"] for st in with_fuel] + [total]
    max_gap = max(b - a for a, b in zip(marks, marks[1:])) if len(marks) > 1 else total
    result = {
        "route_id": route["route_id"], "fuel": fuel, "date": day, "source": source,
        "stations": dedup, "stations_with_fuel": len(with_fuel), "max_gap_km": round(max_gap, 1),
        "availability_note": "наличие топлива — мок (открытых данных нет)",
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
           "lon": round(s["lon"], 3)} for s in res["stations"]]
    # Длинный список сокращаем: оставляем станции с топливом равномерно и все «пустые».
    if len(st) > 10:
        st = [s for s in st if not s["has"]][:3] + [s for s in st if s["has"]][:: max(1, len(st) // 7)]
        st.sort(key=lambda s: s["km"])
    out = {"fuel": fuel, "stations": st, "with_fuel": res["stations_with_fuel"], "max_gap_km": res["max_gap_km"]}
    if res.get("warning"):
        out["warning"] = res["warning"]
    return out


TOOL = Tool(
    name="find_fuel_stations",
    description="АЗС вдоль построенного маршрута (OSM) и наличие топлива на дату (мок). Обязателен для поездок на машине.",
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
