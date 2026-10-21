"""Жильё: офлайн-датасет (открытых API у Островка/Твила нет) с моком свободных мест."""
from __future__ import annotations

from ..geo import haversine_km
from .base import Tool, ToolContext, load_data, parse_date, stable_hash
from .geocode import gazetteer_lookup


async def find_lodging(args: dict, ctx: ToolContext) -> dict:
    items = load_data("lodging.json")
    area = str(args.get("area") or "").lower()
    lat, lon = args.get("near_lat"), args.get("near_lon")
    if (lat is None or lon is None) and area:
        hit = gazetteer_lookup(area)
        if hit:
            lat, lon = hit
    night = parse_date(args.get("date"), ctx.today).isoformat()
    max_price = args.get("max_price_rub")
    rows = []
    for h in items:
        dist = haversine_km(lat, lon, h["lat"], h["lon"]) if lat is not None and lon is not None else None
        if dist is None and area and area not in h["area"].lower():
            continue
        if dist is not None and dist > 70:
            continue
        if max_price and h["price_rub"] > float(max_price):
            continue
        free = stable_hash(h["id"], night) % 5 != 0  # ~20% вариантов заняты на эту ночь
        rows.append({**h, "date": night, "available": free, "distance_km": round(dist, 1) if dist is not None else None})
    rows.sort(key=lambda r: (not r["available"], r["distance_km"] if r["distance_km"] is not None else 0))
    ctx.sources.add("датасет жилья (мок, по мотивам Островок/Tvil)")
    return {"date": night, "options": rows[:6], "note": "цены и наличие — офлайн-мок"}


def _compact(res: dict) -> dict:
    return {"date": res["date"], "options": [
        {"id": r["id"], "name": r["name"], "price_rub": r["price_rub"], "free": r["available"],
         "lat": r["lat"], "lon": r["lon"], **({"km": r["distance_km"]} if r["distance_km"] is not None else {})}
        for r in res["options"][:4]
    ]}


TOOL = Tool(
    name="find_lodging",
    description="Варианты ночёвки рядом с точкой/районом на конкретную ночь: цена и есть ли свободные места.",
    parameters={
        "type": "object",
        "properties": {
            "area": {"type": "string"}, "near_lat": {"type": "number"}, "near_lon": {"type": "number"},
            "date": {"type": "string", "description": "дата заезда YYYY-MM-DD"},
            "max_price_rub": {"type": "number"},
        },
        "required": ["date"],
    },
    handler=find_lodging,
    compactor=_compact,
)
