"""Прогноз погоды: Open-Meteo (реальный открытый API, без ключа)."""
from __future__ import annotations

from datetime import date, timedelta

from ..http import cached_json
from .base import Tool, ToolContext, parse_date, stable_hash

WMO = {
    0: "ясно", 1: "преимущественно ясно", 2: "переменная облачность", 3: "пасмурно", 45: "туман", 48: "изморозь",
    51: "морось", 53: "морось", 55: "сильная морось", 61: "небольшой дождь", 63: "дождь", 65: "ливень",
    66: "ледяной дождь", 67: "ледяной дождь", 71: "небольшой снег", 73: "снег", 75: "сильный снег", 77: "снежные зёрна",
    80: "ливневый дождь", 81: "ливни", 82: "сильные ливни", 85: "снегопад", 86: "сильный снегопад",
    95: "гроза", 96: "гроза с градом", 99: "гроза с градом",
}

FORECAST_DAYS = 16


def _risk(day: dict) -> list[str]:
    flags = []
    if (day.get("precip_mm") or 0) >= 5 or (day.get("precip_prob") or 0) >= 70:
        flags.append("дождь")
    if (day.get("wind_max_ms") or 0) >= 10:
        flags.append("сильный ветер")
    if (day.get("tmax") or 0) <= -10:
        flags.append("мороз")
    if (day.get("code") or 0) >= 95:
        flags.append("гроза")
    return flags


def _offline_forecast(lat: float, lon: float, start: date, end: date) -> list[dict]:
    out = []
    d = start
    while d <= end:
        h = stable_hash(round(lat, 1), round(lon, 1), d.isoformat())
        rainy = h % 4 == 0
        out.append({
            "date": d.isoformat(), "code": 63 if rainy else 2, "summary": "дождь" if rainy else "переменная облачность",
            "tmax": 8 + h % 10, "tmin": 1 + h % 6, "precip_mm": 9.0 if rainy else 0.0, "precip_prob": 80 if rainy else 10,
            "wind_max_ms": 4 + h % 8, "sunrise": "07:20", "sunset": "17:50",
        })
        d += timedelta(1)
    return out


async def get_weather(args: dict, ctx: ToolContext) -> dict:
    lat, lon = float(args["lat"]), float(args["lon"])
    start = parse_date(args.get("start_date"), ctx.today)
    end = parse_date(args.get("end_date"), start)
    end = max(end, start)
    horizon = ctx.today + timedelta(FORECAST_DAYS - 1)
    note = None
    if start > horizon:
        return {"lat": lat, "lon": lon, "days": [], "note": f"прогноз доступен только до {horizon.isoformat()}; учитывай климатическую норму"}
    if end > horizon:
        end, note = horizon, f"прогноз обрезан до {horizon.isoformat()}"

    if ctx.offline:
        days = _offline_forecast(lat, lon, start, end)
        source = "offline"
    else:
        try:
            params = {
                "latitude": round(lat, 3), "longitude": round(lon, 3),
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
                         "precipitation_probability_max,wind_speed_10m_max,sunrise,sunset",
                "wind_speed_unit": "ms", "timezone": "Asia/Vladivostok",
                "start_date": start.isoformat(), "end_date": end.isoformat(),
            }
            if not ctx.compact:
                params["hourly"] = "temperature_2m,precipitation"
            data = await cached_json("GET", "https://api.open-meteo.com/v1/forecast", params=params, ttl=3600)
            dl = data["daily"]
            days = []
            for i, day_s in enumerate(dl["time"]):
                code = dl["weather_code"][i]
                days.append({
                    "date": day_s, "code": code, "summary": WMO.get(code, "—"),
                    "tmax": dl["temperature_2m_max"][i], "tmin": dl["temperature_2m_min"][i],
                    "precip_mm": dl["precipitation_sum"][i], "precip_prob": dl["precipitation_probability_max"][i],
                    "wind_max_ms": dl["wind_speed_10m_max"][i],
                    "sunrise": (dl["sunrise"][i] or "")[11:16], "sunset": (dl["sunset"][i] or "")[11:16],
                })
            source = "open-meteo"
            ctx.sources.add("Open-Meteo")
            raw_hourly = data.get("hourly")
        except Exception as exc:
            days = _offline_forecast(lat, lon, start, end)
            source, note = "offline", f"Open-Meteo недоступен ({str(exc)[:60]}), синтетический прогноз"
            raw_hourly = None
    for d in days:
        d["risks"] = _risk(d)
    ctx.weather[f"{lat:.2f},{lon:.2f}"] = {d["date"]: d for d in days}
    result = {"lat": lat, "lon": lon, "source": source, "days": days}
    if note:
        result["note"] = note
    if not ctx.compact and not ctx.offline and source == "open-meteo" and raw_hourly:
        result["hourly"] = raw_hourly  # бейзлайн честно тащит всё в контекст
    return result


def _compact(res: dict) -> dict:
    days = [
        {"date": d["date"], "sky": d["summary"], "t": f"{d['tmin']:.0f}..{d['tmax']:.0f}°C",
         "rain_mm": d["precip_mm"], "wind_ms": d["wind_max_ms"], "sunset": d["sunset"],
         **({"risks": d["risks"]} if d["risks"] else {})}
        for d in res.get("days", [])
    ]
    out = {"days": days}
    if res.get("note"):
        out["note"] = res["note"]
    return out


TOOL = Tool(
    name="get_weather",
    description="Прогноз погоды Open-Meteo по дням (осадки, ветер, закат) для точки и дат поездки. До 16 дней вперёд.",
    parameters={
        "type": "object",
        "properties": {
            "lat": {"type": "number"}, "lon": {"type": "number"},
            "start_date": {"type": "string", "description": "YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "YYYY-MM-DD"},
        },
        "required": ["lat", "lon", "start_date"],
    },
    handler=get_weather,
    compactor=_compact,
)
