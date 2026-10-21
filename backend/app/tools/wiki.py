"""Справка о месте: Википедия (реальный REST API)."""
from __future__ import annotations

from urllib.parse import quote

from ..http import cached_json
from .base import Tool, ToolContext


async def place_info(args: dict, ctx: ToolContext) -> dict:
    title = str(args.get("title", "")).strip()
    if not title:
        return {"error": "пустой title"}
    if ctx.offline:
        return {"title": title, "extract": "", "note": "offline"}
    try:
        data = await cached_json("GET", f"https://ru.wikipedia.org/api/rest_v1/page/summary/{quote(title)}", ttl=86400)
        ctx.sources.add("Wikipedia")
        return {"title": data.get("title", title), "extract": data.get("extract", "")[:1200],
                "url": data.get("content_urls", {}).get("desktop", {}).get("page")}
    except Exception as exc:
        return {"title": title, "error": f"нет статьи ({str(exc)[:60]})"}


TOOL = Tool(
    name="place_info",
    description="Короткая справка из Википедии о месте/городе, чтобы описать, чем оно интересно. Необязательный тул.",
    parameters={"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]},
    handler=place_info,
    compactor=lambda r: {"title": r.get("title"), "extract": (r.get("extract") or "")[:400], **({"error": r["error"]} if r.get("error") else {})},
)
