"""Автобусы, электрички, паромы: офлайн-расписание (по мотивам Яндекс Расписаний)."""
from __future__ import annotations

from .base import WEEKDAYS_RU, Tool, ToolContext, load_data, parse_date


def _match_stop(name: str, stops: dict) -> str | None:
    q = name.lower().replace("ё", "е")
    for stop in stops:
        s = stop.lower().replace("ё", "е")
        if s in q or q in s or s.split()[0][:6] in q:
            return stop
    return None


def get_trip(trip_id: str) -> dict | None:
    data = load_data("transport.json")
    base, _, direction = trip_id.partition(":")
    route = next((r for r in data["routes"] if r["id"] == base), None)
    if not route:
        return None
    return {**route, "direction": direction or "there"}


async def public_transport(args: dict, ctx: ToolContext) -> dict:
    data = load_data("transport.json")
    stops = data["stops"]
    src = _match_stop(str(args.get("from") or "Владивосток"), stops)
    dst = _match_stop(str(args.get("to") or ""), stops)
    day = parse_date(args.get("date"), ctx.today)
    kind = args.get("type")
    if not src or not dst:
        return {"error": f"нет остановки: from={args.get('from')} to={args.get('to')}", "known_stops": list(stops)}
    trips = []
    for r in data["routes"]:
        if kind and r["type"] != kind:
            continue
        if (r["from"], r["to"]) == (src, dst):
            direction = "there"
        elif (r["from"], r["to"]) == (dst, src):
            direction = "back"
        else:
            continue
        runs = day.weekday() in r["days"]
        trip = {
            "trip_id": f"{r['id']}:{direction}", "type": r["type"], "title": r.get("title", f"{src} → {dst}"),
            "from": src, "to": dst, "departures": r["departures"] if runs else [],
            "last_departure": r["departures"][-1] if runs else None, "duration_min": r["duration_min"],
            "price_rub": r["price_rub"], "runs_on_date": runs,
            "runs_on": ", ".join(WEEKDAYS_RU[d] for d in r["days"]),
        }
        ctx.transport_trips[trip["trip_id"]] = trip
        trips.append(trip)
    ctx.sources.add("расписание транспорта (офлайн-датасет)")
    res = {"date": day.isoformat(), "from": src, "to": dst, "trips": trips,
           "stops": {src: stops[src], dst: stops[dst]}, "note": data["note"]}
    if not trips:
        res["warning"] = "прямых рейсов нет — нужна пересадка во Владивостоке или другой транспорт"
    return res


def _compact(res: dict) -> dict:
    if res.get("error"):
        return {"error": res["error"], "known_stops": res.get("known_stops")}
    out = {"date": res["date"], "trips": [
        {k: t[k] for k in ("trip_id", "type", "departures", "last_departure", "duration_min", "price_rub", "runs_on_date")}
        for t in res["trips"]
    ]}
    if res.get("warning"):
        out["warning"] = res["warning"]
    return out


TOOL = Tool(
    name="public_transport",
    description="Расписание автобусов, электричек и паромов между населёнными пунктами Приморья на дату (туда и обратно).",
    parameters={
        "type": "object",
        "properties": {
            "from": {"type": "string"}, "to": {"type": "string"},
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "type": {"type": "string", "enum": ["bus", "train", "ferry"]},
        },
        "required": ["from", "to", "date"],
    },
    handler=public_transport,
    compactor=_compact,
)
