"""События на даты поездки: офлайн-датасет (KudaGo не покрывает Приморье)."""
from __future__ import annotations

from datetime import timedelta

from .base import Tool, ToolContext, load_data, parse_date


async def find_events(args: dict, ctx: ToolContext) -> dict:
    start = parse_date(args.get("start_date"), ctx.today)
    end = max(parse_date(args.get("end_date"), start), start)
    area = str(args.get("area") or "").lower()
    found = []
    d = start
    while d <= end and (d - start).days < 14:
        for ev in load_data("events.json"):
            if area and area not in ev["area"].lower() and ev["area"].lower() not in area:
                continue
            if d.weekday() in ev["weekdays"] and d.month in ev["months"]:
                found.append({"date": d.isoformat(), "title": ev["title"], "time": ev["time"], "area": ev["area"]})
        d += timedelta(1)
    ctx.sources.add("афиша событий (офлайн-датасет)")
    return {"events": found[:10]}


TOOL = Tool(
    name="find_events",
    description="События и активности (ярмарки, спектакли, кормления, фестивали) в районе на даты поездки.",
    parameters={
        "type": "object",
        "properties": {
            "area": {"type": "string"},
            "start_date": {"type": "string"}, "end_date": {"type": "string"},
        },
        "required": ["start_date"],
    },
    handler=find_events,
    compactor=lambda r: r,
)
