"""Где поесть: реальные кафе и рестораны из OpenStreetMap (Nominatim) с кухней, часами и сайтом."""
from __future__ import annotations

from ..geo import haversine_km
from ..links import yandex_maps
from .base import Tool, ToolContext
from .geocode import _nominatim_raw, gazetteer_lookup

# Кухня из запроса → теги OSM cuisine.
CUISINES = {
    "море": ("seafood", "fish"), "рыб": ("seafood", "fish"), "краб": ("seafood",), "гребеш": ("seafood",),
    "корей": ("korean",), "япон": ("japanese", "sushi"), "суши": ("sushi", "japanese"), "китай": ("chinese",),
    "грузин": ("georgian",), "кавказ": ("georgian", "caucasian", "armenian", "kebab"), "итальян": ("italian", "pizza"),
    "пицц": ("pizza",), "русск": ("russian",), "вьетнам": ("vietnamese",), "бургер": ("burger",), "кофе": ("coffee_shop",),
    "вегет": ("vegetarian", "vegan"), "азиат": ("asian", "korean", "japanese", "chinese", "vietnamese", "thai"),
}
CUISINE_RU = {"seafood": "морепродукты", "fish": "рыба", "korean": "корейская", "japanese": "японская", "sushi": "суши",
              "chinese": "китайская", "georgian": "грузинская", "italian": "итальянская", "pizza": "пицца",
              "russian": "русская", "vietnamese": "вьетнамская", "burger": "бургеры", "coffee_shop": "кофейня",
              "asian": "азиатская", "kebab": "кебаб", "armenian": "армянская", "caucasian": "кавказская",
              "regional": "местная", "vegetarian": "вегетарианская", "thai": "тайская", "middle_eastern": "ближневосточная", "peruvian": "перуанская",
              "steak_house": "стейки", "ramen": "рамен", "noodle": "лапша", "uzbek": "узбекская", "european": "европейская"}


def _wanted(cuisine: str) -> set[str]:
    c = cuisine.lower()
    return {tag for key, tags in CUISINES.items() if key in c for tag in tags}


async def find_food(args: dict, ctx: ToolContext) -> dict:
    lat, lon = args.get("near_lat"), args.get("near_lon")
    if (lat is None or lon is None) and args.get("area"):
        hit = gazetteer_lookup(str(args["area"]))
        if hit:
            lat, lon = hit
    if lat is None or lon is None:
        return {"error": "нужны near_lat/near_lon или area"}
    lat, lon = float(lat), float(lon)
    cuisine = str(args.get("cuisine") or "")
    wanted = _wanted(cuisine)
    found: dict[str, dict] = {}
    if not ctx.offline:
        for radius in (0.02, 0.06):  # сначала рядом, потом шире
            for q in ("ресторан", "кафе"):
                try:
                    rows = await _nominatim_raw(q, (lon - radius * 1.4, lat + radius, lon + radius * 1.4, lat - radius))
                except Exception:
                    rows = []
                for r in rows:
                    name = r.get("name") or ""
                    if not name or name in found:
                        continue
                    e = r.get("extratags") or {}
                    tags = [t.strip() for t in (e.get("cuisine") or "").split(";") if t.strip()]
                    plat, plon = float(r["lat"]), float(r["lon"])
                    found[name] = {
                        "name": name, "lat": round(plat, 5), "lon": round(plon, 5),
                        "cuisine": ", ".join(CUISINE_RU.get(t, t) for t in tags) or None,
                        "match": bool(wanted & set(tags)), "hours": e.get("opening_hours"),
                        "url": e.get("website") or e.get("contact:website"),
                        "map_url": yandex_maps(name, plat, plon),
                        "km": round(haversine_km(lat, lon, plat, plon), 1),
                    }
            if sum(1 for f in found.values() if f["match"] or not wanted) >= 3:
                break
        if found:
            ctx.sources.add("OpenStreetMap / Nominatim (кафе и рестораны)")
    places = sorted(found.values(), key=lambda f: (not f["match"], f["km"]))[: int(args.get("limit") or 6)]
    search = f"{cuisine or 'кафе'} рестораны".strip()
    res = {"places": places, "search_url": yandex_maps(search, lat, lon, zoom=14)}
    if wanted and not any(p["match"] for p in places):
        res["note"] = f"с кухней «{cuisine}» рядом в OSM не нашлось — показаны ближайшие заведения и ссылка на поиск"
    if not places:
        res["note"] = "заведения не найдены — предложи поиск по ссылке search_url"
    return res


def _compact(res: dict) -> dict:
    if res.get("error"):
        return res
    out = {"places": [{k: p[k] for k in ("name", "lat", "lon", "cuisine", "hours", "url", "km") if p.get(k)} for p in res["places"]]}
    if res.get("note"):
        out["note"] = res["note"]
    return out


TOOL = Tool(
    name="find_food",
    description=("Реальные кафе и рестораны рядом с точкой (OpenStreetMap): название, кухня, часы, сайт. "
                 "Используй для каждого приёма пищи в плане и ставь в item name, lat, lon, url."),
    parameters={
        "type": "object",
        "properties": {
            "near_lat": {"type": "number"}, "near_lon": {"type": "number"}, "area": {"type": "string"},
            "cuisine": {"type": "string", "description": "предпочтение по кухне: морепродукты, корейская, грузинская…"},
            "limit": {"type": "integer"},
        },
    },
    handler=find_food,
    compactor=_compact,
)
