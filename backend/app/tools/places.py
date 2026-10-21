"""Поиск достопримечательностей: офлайн-датасет Приморья с режимом работы."""
from __future__ import annotations

from datetime import date, timedelta

from ..geo import haversine_km
from .base import WEEKDAYS_RU, Tool, ToolContext, load_data, parse_date
from .geocode import gazetteer_lookup


def is_open(place: dict, day: date) -> bool:
    return day.weekday() not in place.get("closed_weekdays", [])


def hours_text(place: dict) -> str:
    h = place.get("hours")
    base = "круглосуточно" if not h else f"{h['open']}–{h['close']}"
    closed = place.get("closed_weekdays") or []
    if closed:
        base += ", выходной: " + ", ".join(WEEKDAYS_RU[d] for d in closed)
    return base


def get_place(place_id: str) -> dict | None:
    return next((p for p in load_data("places.json") if p["id"] == place_id), None)


async def search_places(args: dict, ctx: ToolContext) -> dict:
    places = load_data("places.json")
    interests = [str(i).lower() for i in (args.get("interests") or [])]
    area = str(args.get("area") or "").lower().strip()
    limit = max(1, min(int(args.get("limit") or 8), 20))
    radius = float(args.get("radius_km") or 0)
    lat, lon = args.get("near_lat"), args.get("near_lon")
    if (lat is None or lon is None) and area:
        hit = gazetteer_lookup(area)
        if hit:
            lat, lon = hit
            radius = radius or (110 if ("район" in area or "округ" in area) else 60)
    start = parse_date(args.get("start_date"), ctx.today)
    end = parse_date(args.get("end_date"), start)
    if end < start:
        end = start
    days = [start + timedelta(d) for d in range((end - start).days + 1)][:7]

    # Если район назван явно и в нём достаточно мест — ищем только в нём.
    by_area = [p for p in places if area and (area in p["area"].lower() or p["area"].lower() in area)]
    if len(by_area) >= 3 and ("район" in area or "округ" in area):
        places, radius = by_area, 0
    scored = []
    for p in places:
        dist = haversine_km(lat, lon, p["lat"], p["lon"]) if lat is not None and lon is not None else None
        if radius and dist is not None and dist > radius:
            continue
        if area and dist is None and area not in p["area"].lower() and area not in p["name"].lower():
            continue
        text = " ".join([p["name"], p["desc"], " ".join(p["tags"]), p["kind"]]).lower()
        score = sum(2 for i in interests if i in text) + (1 if not interests else 0)
        if dist is not None:
            score -= dist / 50
        scored.append((score, dist, p))
    scored.sort(key=lambda t: -t[0])

    results = []
    for score, dist, p in scored[:limit]:
        ctx.places_seen[p["id"]] = p
        results.append({
            **p,
            "hours_text": hours_text(p),
            "distance_km": round(dist, 1) if dist is not None else None,
            "open_on": {d.isoformat(): is_open(p, d) for d in days},
        })
    ctx.sources.add("датасет мест Приморья (режим работы — офлайн)")
    return {"count": len(results), "places": results}


def _compact(res: dict) -> dict:
    out = []
    for p in res.get("places", []):
        closed_dates = [d for d, ok in p["open_on"].items() if not ok]
        item = {
            "id": p["id"], "name": p["name"], "lat": round(p["lat"], 4), "lon": round(p["lon"], 4),
            "hours": p["hours_text"], "visit_h": p["visit_h"], "outdoor": p["outdoor"],
        }
        if closed_dates:
            item["closed_on"] = closed_dates
        if p.get("distance_km") is not None:
            item["km"] = p["distance_km"]
        for extra in ("season", "access_note"):
            if p.get(extra):
                item[extra] = p[extra]
        out.append(item)
    return {"places": out}


TOOL = Tool(
    name="search_places",
    description=(
        "Найти достопримечательности Приморья по району/интересам. Возвращает id, координаты, "
        "режим работы и открыто ли место в каждую дату поездки. Используй только места из этого тула."
    ),
    parameters={
        "type": "object",
        "properties": {
            "area": {"type": "string", "description": "Город или район: Владивосток, Находка, остров Русский, Хасанский район…"},
            "interests": {"type": "array", "items": {"type": "string"}, "description": "море, история, поход, дети, пляж, животные…"},
            "near_lat": {"type": "number"},
            "near_lon": {"type": "number"},
            "radius_km": {"type": "number"},
            "start_date": {"type": "string", "description": "YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            "limit": {"type": "integer"},
        },
    },
    handler=search_places,
    compactor=_compact,
)
