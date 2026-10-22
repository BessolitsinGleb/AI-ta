"""Сверка плана с запросом и с реальным миром. Любое противоречие — ошибка.

Проверки независимы от LLM: погоду валидатор при необходимости запрашивает сам,
режим работы и расписания берёт из датасетов, расстояния считает по координатам.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from .geo import haversine_km, in_primorye
from .intents import Intents
from .tools.base import WEEKDAYS_RU, ToolContext, load_data, parse_date, stable_hash
from .tools.places import get_place, hours_text, is_open
from .tools.routing import DAILY_LIMIT_KM, ROAD_FACTOR
from .tools.transport import get_trip
from .tools.weather import FORECAST_DAYS, get_weather


@dataclass
class Check:
    id: str
    ok: bool
    text: str
    severity: str = "error"  # error | warn

    def dict(self) -> dict:
        return asdict(self)


def _t(value: str | None) -> int | None:
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})", str(value or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _coords(item: dict) -> tuple[float, float] | None:
    try:
        lat, lon = float(item.get("lat")), float(item.get("lon"))
    except (TypeError, ValueError):
        place = get_place(str(item.get("place_id") or ""))
        return (place["lat"], place["lon"]) if place else None
    return lat, lon


MODE_RU = {"car": "машина", "bike": "велосипед", "foot": "пешком", "bus": "автобус", "train": "поезд"}
# Еда — рядом с тем, что смотрим: от соседней точки дня не дальше (км по дорогам)
FOOD_NEAR_KM = {"foot": 1.5, "bike": 4.0, "bus": 2.0, "train": 2.0, "car": 8.0}


def plan_transport(plan: dict, intents: Intents) -> str:
    mode = str(plan.get("transport") or intents.transport or "car").lower()
    return {"walk": "foot", "walking": "foot", "bicycle": "bike", "public": "bus", "mixed": "bus"}.get(mode, mode)


async def validate_plan(plan: dict, intents: Intents, ctx: ToolContext) -> list[Check]:
    checks: list[Check] = []
    days = plan.get("days") or []
    mode = plan_transport(plan, intents)

    if not days:
        return [Check("structure", False, "В плане нет ни одного дня")]

    # 1. Сроки из запроса.
    if intents.max_days:
        checks.append(Check("days_limit", len(days) <= intents.max_days,
                            f"Дней в плане: {len(days)}, просили не больше {intents.max_days}"))
    if intents.start_date:
        want_s = date.fromisoformat(intents.start_date)
        want_e = date.fromisoformat(intents.end_date or intents.start_date)
        got = [parse_date(d.get("date"), date.min) for d in days]
        inside = all(want_s <= g <= want_e for g in got)
        checks.append(Check("dates", inside, f"Даты плана {', '.join(g.isoformat() for g in got)}; "
                                             f"ожидались {want_s.isoformat()}…{want_e.isoformat()}"))
    if intents.transport:
        same = mode == intents.transport or (intents.transport in ("bus", "train") and mode in ("bus", "train"))
        checks.append(Check("transport", same, f"Транспорт в плане: {MODE_RU.get(mode, mode)}, в запросе: "
                                               f"{MODE_RU.get(intents.transport, intents.transport)}"))

    empty = [str(i + 1) for i, d in enumerate(days)
             if not any((it.get("type") in ("place", "food", "note")) for it in d.get("items") or [])]
    checks.append(Check("non_empty_days", not empty, "В каждом дне есть занятия" if not empty else
                        f"Пустые дни: {', '.join(empty)}"))

    # 2. Ночёвка.
    nights = [d for d in days[:-1]]
    if intents.overnight:
        missing = [str(i + 1) for i, d in enumerate(nights) if not (d.get("lodging") or {}).get("name")]
        ok = len(days) >= 2 and not missing
        checks.append(Check("overnight", ok, "Ночёвка есть на каждую ночь" if ok else
                            ("Просили с ночёвкой, а план на один день" if len(days) < 2 else f"Нет ночёвки после дня {', '.join(missing)}")))
    for i, d in enumerate(nights):
        lod = d.get("lodging") or {}
        lid = lod.get("lodging_id") or lod.get("id")
        if lid:
            known = next((h for h in load_data("lodging.json") if h["id"] == lid), None)
            night = parse_date(d.get("date"), ctx.today).isoformat()
            free = known is not None and stable_hash(known["id"], night) % 5 != 0
            checks.append(Check(f"lodging_{i+1}", free, f"Ночёвка «{lod.get('name')}» {night}: " +
                                ("есть места" if free else ("нет в базе" if not known else "мест нет"))))

    # 3. Места: регион, режим работы, время визита.
    outside, closed, unknown = [], [], []
    for d in days:
        day = parse_date(d.get("date"), ctx.today)
        for it in d.get("items") or []:
            c = _coords(it)
            if c and not in_primorye(*c):
                outside.append(it.get("name", "?"))
            pid = it.get("place_id")
            if not pid:
                continue
            place = get_place(str(pid))
            if not place:
                unknown.append(it.get("name") or pid)
                continue
            if not is_open(place, day):
                closed.append(f"{place['name']} ({day.isoformat()}, {WEEKDAYS_RU[day.weekday()]}: выходной)")
                continue
            t, h = _t(it.get("time")), place.get("hours")
            if t is not None and h and not (_t(h["open"]) <= t <= _t(h["close"]) - 30):
                closed.append(f"{place['name']} в {it.get('time')} (работает {hours_text(place)})")
    checks.append(Check("region", not outside, "Все точки в Приморском крае" if not outside else
                        "Вне Приморья: " + ", ".join(outside[:3])))
    checks.append(Check("opening_hours", not closed, "Все места открыты в выбранные дни и часы" if not closed else
                        "Закрыто: " + "; ".join(closed[:3])))
    if unknown:
        checks.append(Check("known_places", False, "Места не из базы (режим не проверить): " + ", ".join(unknown[:3]), "warn"))

    # 4. Расстояния по силам транспорта.
    total_km = 0.0
    for i, d in enumerate(days):
        pts = [c for c in (_coords(it) for it in d.get("items") or []) if c]
        lod = d.get("lodging") or {}
        if lod.get("lat") and lod.get("lon"):
            pts.append((float(lod["lat"]), float(lod["lon"])))
        km = sum(haversine_km(*pts[j], *pts[j + 1]) for j in range(len(pts) - 1)) * ROAD_FACTOR
        total_km += km
        limit = DAILY_LIMIT_KM.get(mode)
        if limit and mode in ("foot", "bike"):
            checks.append(Check(f"distance_day{i+1}", km <= limit,
                                f"День {i+1}: ~{km:.0f} км {'пешком' if mode == 'foot' else 'на велосипеде'} (предел {limit:.0f})"))

    # 4б. Кафе рядом с местами дня, а не в соседнем посёлке.
    near_km = FOOD_NEAR_KM.get(mode, 8.0)
    far_food, food_seen = [], False
    for d in days:
        stops = [it for it in d.get("items") or [] if it.get("type") != "transfer"]
        lod = d.get("lodging") or {}
        if lod.get("lat") and lod.get("lon"):
            stops.append({"name": lod.get("name"), "lat": lod["lat"], "lon": lod["lon"], "type": "lodging"})
        for j, it in enumerate(stops):
            if it.get("type") != "food" or not (c := _coords(it)):
                continue
            food_seen = True
            near = [(o, oc) for o in (stops[j - 1] if j else None, stops[j + 1] if j + 1 < len(stops) else None)
                    if o and (oc := _coords(o))]
            if not near:
                continue
            other, oc = min(near, key=lambda x: haversine_km(*c, *x[1]))
            km = haversine_km(*c, *oc) * ROAD_FACTOR
            if km > near_km:
                far_food.append(f"«{it.get('name')}» в ~{km:.0f} км от «{other.get('name')}»")
    if food_seen:
        checks.append(Check("food_nearby", not far_food, "Кафе рядом с местами дня" if not far_food else
                            f"Еда далеко от маршрута (нужно ближе {near_km:g} км): " + "; ".join(far_food[:3])))

    # 5. Погода — сверяем с прогнозом сами.
    horizon = ctx.today + timedelta(FORECAST_DAYS - 1)
    bad_weather = []
    rain_aware = re.search(r"дожд|ливн|осадк|зонт|непогод|ветер|ветр", " ".join(map(str, plan.get("cautions") or [])) +
                           " ".join(map(str, plan.get("weather_notes") or [])), re.I)
    for i, d in enumerate(days):
        day = parse_date(d.get("date"), ctx.today)
        if day > horizon or day < ctx.today:
            continue
        pts = [c for c in (_coords(it) for it in d.get("items") or []) if c]
        if not pts:
            continue
        lat, lon = pts[len(pts) // 2]
        key = f"{lat:.2f},{lon:.2f}"
        forecast = ctx.weather.get(key, {}).get(day.isoformat())
        if forecast is None:
            res = await get_weather({"lat": lat, "lon": lon, "start_date": day.isoformat(), "end_date": day.isoformat()}, ctx)
            forecast = next((x for x in res.get("days", []) if x["date"] == day.isoformat()), None)
        if not forecast:
            continue
        d["_forecast"] = forecast
        risks = forecast.get("risks") or []
        if risks and mode in ("bike", "foot"):
            bad_weather.append(f"день {i+1}: {', '.join(risks)} — {'велосипед' if mode == 'bike' else 'пеший маршрут'}")
        elif risks and not rain_aware:
            bad_weather.append(f"день {i+1}: {', '.join(risks)}, а в плане это не учтено")
        # Уличные места после заката — в любом режиме.
        sunset = _t(forecast.get("sunset"))
        for it in d.get("items") or []:
            place = get_place(str(it.get("place_id") or ""))
            t = _t(it.get("time"))
            if place and place.get("outdoor") and place.get("visit_h", 0) >= 1 and t is not None and sunset is not None \
                    and t + place["visit_h"] * 60 > sunset + 20:
                bad_weather.append(f"«{place['name']}» в {it.get('time')} (~{place['visit_h']:g} ч) — закончится "
                                   f"в темноте (закат {forecast['sunset']})")
        # Светлое время для пеших и вело.
        if mode in ("bike", "foot"):
            last = max([t for t in (_t(it.get("time")) for it in d.get("items") or []) if t is not None], default=None)
            sunset = _t(forecast.get("sunset"))
            if last is not None and sunset is not None and last > sunset:
                bad_weather.append(f"день {i+1}: активность в {last // 60:02d}:{last % 60:02d} после заката {forecast['sunset']}")
    checks.append(Check("weather", not bad_weather, "План учитывает прогноз погоды" if not bad_weather else
                        "Погода: " + "; ".join(bad_weather[:3])))

    # 6. Машина: заправки на длинных маршрутах.
    if mode == "car" and total_km > 150:
        fuel_checked = bool(ctx.fuel) or bool(plan.get("fuel_stops"))
        checks.append(Check("fuel", fuel_checked, f"~{total_km:.0f} км за поездку: " +
                            ("АЗС с топливом по пути проверены" if fuel_checked else "не проверено, где заправиться")))
        gaps = [f for f in ctx.fuel.values() if f.get("max_gap_km", 0) > 200]
        if gaps:
            checks.append(Check("fuel_gap", False, f"Перегон без топлива {gaps[0]['max_gap_km']:.0f} км", "warn"))

    # 7. Общественный транспорт: рейсы существуют, ходят в этот день, успеваем на последний.
    if mode in ("bus", "train"):
        used = 0
        problems = []
        for d in days:
            day = parse_date(d.get("date"), ctx.today)
            for it in d.get("items") or []:
                tid = it.get("trip_id")
                if not tid:
                    continue
                used += 1
                trip = get_trip(str(tid))
                if not trip:
                    problems.append(f"рейса {tid} нет в расписании")
                elif day.weekday() not in trip["days"]:
                    problems.append(f"{trip.get('title', tid)} не ходит {day.isoformat()}")
                else:
                    t = _t(it.get("time"))
                    deps = [_t(x) for x in trip["departures"] if _t(x) is not None]
                    if t is not None and deps and t > max(deps):
                        problems.append(f"{it.get('time')} — позже последнего рейса {trip['departures'][-1]}")
        checks.append(Check("schedule", used > 0 and not problems,
                            "Рейсы сверены с расписанием" if used and not problems else
                            ("; ".join(problems[:3]) if problems else "В плане нет ни одного рейса из расписания")))
    return checks


def summarize(checks: list[Check]) -> dict:
    errors = [c for c in checks if not c.ok and c.severity == "error"]
    return {
        "passed": sum(1 for c in checks if c.ok),
        "total": len(checks),
        "errors": len(errors),
        "converges": not errors,
        "score": round(sum(1 for c in checks if c.ok) / len(checks), 3) if checks else 0.0,
    }
