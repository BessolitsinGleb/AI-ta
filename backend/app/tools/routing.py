"""Маршруты: OSRM (реальный роутинг по дорогам OSM) для машины, велосипеда и пешехода."""
from __future__ import annotations

from ..geo import haversine_km, path_length_km
from ..http import cached_json
from .base import Tool, ToolContext, stable_hash

OSRM = {
    "car": "https://router.project-osrm.org/route/v1/driving/",
    "bike": "https://routing.openstreetmap.de/routed-bike/route/v1/driving/",
    "foot": "https://routing.openstreetmap.de/routed-foot/route/v1/driving/",
}
FALLBACK_SPEED_KMH = {"car": 55.0, "bike": 14.0, "foot": 4.5}
ROAD_FACTOR = 1.35  # во сколько раз дорога длиннее прямой (сопки Приморья)

# Ограничения по способу передвижения — их проверяет валидатор плана.
DAILY_LIMIT_KM = {"foot": 20.0, "bike": 80.0, "car": 450.0}


def _normalize_mode(mode: str | None) -> str:
    m = (mode or "car").lower()
    if m in ("walk", "walking", "foot", "пешком"):
        return "foot"
    if m in ("bike", "bicycle", "cycling", "велосипед"):
        return "bike"
    return "car"


def _fallback(points: list[dict], mode: str) -> dict:
    coords = [(p["lat"], p["lon"]) for p in points]
    legs = []
    for a, b in zip(points, points[1:]):
        km = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) * ROAD_FACTOR
        legs.append({"from": a.get("name", ""), "to": b.get("name", ""), "km": round(km, 1),
                     "h": round(km / FALLBACK_SPEED_KMH[mode], 2)})
    total = path_length_km(coords) * ROAD_FACTOR
    return {"distance_km": round(total, 1), "duration_h": round(total / FALLBACK_SPEED_KMH[mode], 2),
            "legs": legs, "geometry": [[lat, lon] for lat, lon in coords], "source": "estimate"}


async def build_route(args: dict, ctx: ToolContext) -> dict:
    mode = _normalize_mode(args.get("mode"))
    points = [p for p in (args.get("points") or []) if p and "lat" in p and "lon" in p][:12]
    if len(points) < 2:
        return {"error": "нужно минимум 2 точки с lat/lon"}
    route_id = f"r{stable_hash(mode, *[(round(p['lat'], 4), round(p['lon'], 4)) for p in points]) % 100000}"
    res: dict
    if ctx.offline:
        res = _fallback(points, mode)
    else:
        coords = ";".join(f"{float(p['lon']):.5f},{float(p['lat']):.5f}" for p in points)
        try:
            data = await cached_json(
                "GET", OSRM[mode] + coords,
                params={"overview": "simplified", "geometries": "geojson", "steps": "false"},
                ttl=86400, timeout=15,
            )
            if data.get("code") != "Ok":
                raise RuntimeError(data.get("code"))
            r = data["routes"][0]
            legs = []
            for i, leg in enumerate(r["legs"]):
                legs.append({"from": points[i].get("name", ""), "to": points[i + 1].get("name", ""),
                             "km": round(leg["distance"] / 1000, 1), "h": round(leg["duration"] / 3600, 2)})
            # OSRM для велосипеда/пешехода иногда даёт нереально быстрое время по паромам — пересчитаем по скорости.
            duration_h = r["duration"] / 3600
            if mode != "car":
                duration_h = max(duration_h, r["distance"] / 1000 / FALLBACK_SPEED_KMH[mode] * 0.8)
            res = {"distance_km": round(r["distance"] / 1000, 1), "duration_h": round(duration_h, 2), "legs": legs,
                   "geometry": [[c[1], c[0]] for c in r["geometry"]["coordinates"]], "source": "osrm"}
            ctx.sources.add("OSRM (OpenStreetMap)")
        except Exception as exc:
            res = _fallback(points, mode)
            res["note"] = f"OSRM недоступен ({str(exc)[:50]}), оценка по прямой ×{ROAD_FACTOR}"
    res.update({"route_id": route_id, "mode": mode, "points": points})
    limit = DAILY_LIMIT_KM.get(mode)
    if limit and res["distance_km"] > limit:
        res["warning"] = f"{res['distance_km']} км больше разумного дневного предела для режима {mode} ({limit:.0f} км)"
    ctx.routes[route_id] = res
    return res


def _compact(res: dict) -> dict:
    if res.get("error"):
        return res
    keep = {k: res[k] for k in ("route_id", "mode", "distance_km", "duration_h", "legs") if k in res}
    for k in ("warning", "note"):
        if res.get(k):
            keep[k] = res[k]
    return keep


TOOL = Tool(
    name="build_route",
    description=(
        "Построить маршрут по дорогам через точки (OSRM). mode: car | bike | foot. "
        "Возвращает расстояние, время по перегонам и route_id (нужен для поиска АЗС)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["car", "bike", "foot"]},
            "points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "lat": {"type": "number"}, "lon": {"type": "number"}},
                    "required": ["lat", "lon"],
                },
            },
        },
        "required": ["mode", "points"],
    },
    handler=build_route,
    compactor=_compact,
)
