"""Геокодер: Nominatim (OSM, реальный API) с фолбэком на офлайн-справочник."""
from __future__ import annotations

import asyncio
import time

from ..geo import PRIMORYE_BBOX, in_primorye
from ..http import cached_json
from .base import Tool, ToolContext, load_data

_last_call = 0.0
_rate_lock = asyncio.Lock()


async def _nominatim_raw(query: str, viewbox: tuple[float, float, float, float], limit: int = 10) -> list[dict]:
    """viewbox = (запад, север, восток, юг)."""
    global _last_call
    async with _rate_lock:  # политика Nominatim — не чаще 1 запроса в секунду
        wait = 1.0 - (time.time() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = time.time()
    w, n, e, s = viewbox
    return await cached_json(
        "GET",
        "https://nominatim.openstreetmap.org/search",
        params={"q": query, "format": "jsonv2", "limit": limit, "viewbox": f"{w},{n},{e},{s}", "bounded": 1,
                "extratags": 1, "accept-language": "ru"},
        ttl=86400,
    )


async def _nominatim(query: str) -> list[dict]:
    s, w, n, e = PRIMORYE_BBOX
    return await _nominatim_raw(query, (w, n, e, s), limit=3)


def gazetteer_lookup(query: str) -> tuple[float, float] | None:
    gaz = load_data("gazetteer.json")
    q = query.lower().replace("ё", "е").strip()
    if not q:
        return None
    best: tuple[int, tuple[float, float]] | None = None
    for name, (lat, lon) in gaz.items():
        n = name.replace("ё", "е")
        if n in q or q in n:
            score = len(n) if n in q else len(q)  # самое длинное совпадение: «хасанский район» важнее «хасан»
            if best is None or score > best[0]:
                best = (score, (lat, lon))
    return best[1] if best else None


async def geocode(args: dict, ctx: ToolContext) -> dict:
    query = str(args.get("query", "")).strip()
    if not query:
        return {"error": "пустой запрос"}
    if not ctx.offline:
        try:
            rows = await _nominatim(query)
            found = []
            for r in rows:
                lat, lon = float(r["lat"]), float(r["lon"])
                if in_primorye(lat, lon):
                    found.append({"name": r.get("display_name", "")[:120], "lat": round(lat, 5), "lon": round(lon, 5)})
            if found:
                ctx.sources.add("Nominatim (OSM)")
                return {"query": query, "results": found, "source": "nominatim"}
        except Exception as exc:  # сеть/лимиты — уходим в офлайн
            err = str(exc)[:80]
        else:
            err = "нет результатов в Приморье"
    else:
        err = "offline"
    hit = gazetteer_lookup(query)
    if hit:
        ctx.sources.add("офлайн-справочник населённых пунктов")
        return {"query": query, "results": [{"name": query, "lat": hit[0], "lon": hit[1]}], "source": "gazetteer"}
    return {"query": query, "results": [], "error": f"не найдено в Приморском крае ({err})"}


def _compact(res: dict) -> dict:
    return {"results": [{k: r[k] for k in ("name", "lat", "lon")} for r in res.get("results", [])[:2]],
            **({"error": res["error"]} if res.get("error") else {})}


TOOL = Tool(
    name="geocode",
    description="Найти координаты населённого пункта или места в Приморском крае (OSM Nominatim).",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Название, например «Находка» или «бухта Витязь»"}},
        "required": ["query"],
    },
    handler=geocode,
    compactor=_compact,
)
