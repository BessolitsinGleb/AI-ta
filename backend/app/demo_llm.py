"""Детерминированный «демо-LLM»: правило-ориентированный планировщик с тем же протоколом tool calling.

Нужен, чтобы приложение и весь агентный цикл работали без ключа OpenRouter (демо, тесты, отладка фронта).
Он ходит в те же тулы, что и настоящая модель, — меняется только «мозг».
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from .guardrails import precheck
from .intents import parse_intents
from .llm import LLMResponse
from .tools.base import load_data
from .tools.geocode import gazetteer_lookup
from .tools.places import get_place, is_open

AREA_ALIASES = [
    ("остров русский", "остров Русский"), ("русск", "остров Русский"), ("находк", "Находка"), ("уссурийск", "Уссурийск"),
    ("хасан", "Хасанский район"), ("андреевк", "Хасанский район"), ("витяз", "Хасанский район"), ("гамов", "Хасанский район"),
    ("леопард", "Хасанский район"), ("ханк", "Ханкайский район"), ("лазо", "Лазовский район"), ("петров", "Лазовский район"),
    ("дальнегорск", "Дальнегорск"), ("сафари", "Шкотовский район"), ("шкотов", "Шкотовский район"),
    ("водопад", "Шкотовский район"), ("пидан", "Партизанский район"), ("партизанск", "Партизанск"),
    ("терне", "Тернейский район"), ("сихотэ", "Тернейский район"), ("удэге", "Красноармейский район"),
    ("ливади", "Находкинский округ"), ("ольг", "Ольгинский район"),
]
AREA_CENTER = {
    "Хасанский район": (42.70, 131.25), "Ханкайский район": (44.76, 132.04), "Лазовский район": (43.20, 133.85),
    "Шкотовский район": (43.25, 132.50), "Партизанский район": (43.10, 132.85), "Тернейский район": (45.05, 136.60),
    "Красноармейский район": (45.86, 134.56), "Находкинский округ": (42.86, 132.67), "Ольгинский район": (43.74, 135.29),
}
TRANSPORT_STOP = {
    "Находка": "Находка", "Уссурийск": "Уссурийск", "Хасанский район": "Андреевка", "Ханкайский район": "Камень-Рыболов",
    "Лазовский район": "Лазо", "Дальнегорск": "Дальнегорск", "Шкотовский район": "Шкотово", "Партизанский район": "Партизанск",
    "Партизанск": "Партизанск", "остров Русский": "остров Русский", "Находкинский округ": "Ливадия", "Ольгинский район": "Ольга",
}
VL = (43.1155, 131.8855)
MODE_RU = {"car": "на машине", "bike": "на велосипеде", "foot": "пешком", "bus": "на автобусе", "train": "на электричке"}


def _hm(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m // 60:02d}:{m % 60:02d}"


def _call(i: int, name: str, args: dict) -> dict:
    return {"id": f"demo_{name}_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


class DemoLLM:
    model = "demo/rule-based-planner"

    async def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        system = messages[0]["content"]
        m = re.search(r"Сегодня (\d{4}-\d{2}-\d{2})", system)
        today = date.fromisoformat(m.group(1)) if m else date.today()
        query = next(x["content"] for x in messages if x["role"] == "user")
        orig = re.search(r"Исходный запрос клиента: (.+)", query)
        change = re.search(r"Клиент просит изменить план: «(.+?)»", query, re.S)
        if orig and change:  # доработка: планируем по исходному запросу с учётом просьбы, без JSON прошлого плана
            query = f"{orig.group(1)}\n{change.group(1)}"
        it = parse_intents(query, today)
        names: dict[str, str] = {}
        results: dict[str, list] = {}
        for msg in messages:
            for c in msg.get("tool_calls") or []:
                names[c["id"]] = c["function"]["name"]
            if msg["role"] == "tool" and msg.get("tool_call_id") in names:
                try:
                    results.setdefault(names[msg["tool_call_id"]], []).append(json.loads(msg["content"]))
                except json.JSONDecodeError:
                    pass
        step = sum(1 for x in messages if x["role"] == "assistant")
        usage = {"prompt_tokens": sum(len(str(x.get("content", ""))) for x in messages) // 4, "completion_tokens": 120}

        def reply(calls: list[dict]) -> LLMResponse:
            return LLMResponse({"role": "assistant", "content": "", "tool_calls": calls}, usage, self.model)

        tool_names = {t["function"]["name"] for t in tools}
        cuisine_m = re.search(r"кухн[^:\n]*:\s*([^\n]+)", query, re.I)
        cuisine = cuisine_m.group(1).strip() if cuisine_m else ""
        verdict = precheck(query)
        if not verdict.allowed:
            return reply([_call(0, "decline_request", {"category": verdict.category if verdict.category in
                                                         ("off_topic", "other_region", "injection") else "off_topic",
                                                         "message": verdict.message})])

        q = query.lower()
        area = next((a for k, a in AREA_ALIASES if k in q), "Владивосток")
        center = AREA_CENTER.get(area) or gazetteer_lookup(area) or VL
        n_days = it.days or it.max_days or (2 if it.overnight else 1)
        n_days = max(1, min(n_days, 3))
        start = date.fromisoformat(it.start_date) if it.start_date else today + timedelta(1)
        dates = [start + timedelta(i) for i in range(n_days)]
        mode = it.transport or "car"
        route_mode = mode if mode in ("car", "bike", "foot") else "car"

        if step == 0 and "ask_user" in tool_names and re.search(r"поесть|еда|кухн|ресторан|кафе|вкусн", q):
            return reply([_call(0, "ask_user", {"questions": [
                {"text": "Какую кухню предпочитаете?", "options": ["Морепродукты", "Корейская", "Грузинская", "Неважно"]}]})])

        if step == 0:
            return reply([
                _call(1, "search_places", {"area": area, "interests": it.interests, "start_date": dates[0].isoformat(),
                                           "end_date": dates[-1].isoformat(), "limit": 10}),
                _call(2, "get_weather", {"lat": center[0], "lon": center[1], "start_date": dates[0].isoformat(),
                                         "end_date": dates[-1].isoformat()}),
            ])

        places_raw = (results.get("search_places") or [{}])[-1].get("places", [])
        places = [get_place(p["id"]) for p in places_raw if get_place(p["id"])]
        weather_days = {d["date"]: d for d in (results.get("get_weather") or [{}])[-1].get("days", [])}
        per_day: list[list[dict]] = []
        used: set[str] = set()
        cap = {"foot": 3, "bike": 3, "car": 3, "bus": 2, "train": 2}.get(mode, 3)
        cap = max(1, min(cap, -(-len(places) // n_days)))  # делим места поровну между днями
        for d in dates:
            wd = weather_days.get(d.isoformat(), {})
            rainy = bool(wd.get("risks"))
            pool = [p for p in places if p["id"] not in used and is_open(p, d)]
            if rainy and mode in ("bike", "foot"):
                pool.sort(key=lambda p: p["outdoor"])
            chosen = pool[:cap]
            used.update(p["id"] for p in chosen)
            per_day.append(chosen)

        if step == 1:
            pts = [{"name": "Владивосток", "lat": VL[0], "lon": VL[1]}] if area != "Владивосток" and route_mode == "car" else []
            pts += [{"name": p["name"], "lat": p["lat"], "lon": p["lon"]} for day in per_day for p in day]
            calls = []
            if len(pts) >= 2:
                calls.append(_call(3, "build_route", {"mode": route_mode, "points": pts}))
            if n_days > 1:
                for i, d in enumerate(dates[:-1]):
                    last = (per_day[i] or places or [{"lat": center[0], "lon": center[1]}])[-1]
                    calls.append(_call(10 + i, "find_lodging", {"near_lat": last["lat"], "near_lon": last["lon"], "date": d.isoformat()}))
            first = next((p for day in per_day for p in day), None)
            if first:
                calls.append(_call(6, "find_food", {"near_lat": first["lat"], "near_lon": first["lon"],
                                                   "cuisine": "" if cuisine.lower() == "неважно" else cuisine}))
            if mode in ("bus", "train") and area != "Владивосток":
                calls.append(_call(4, "public_transport", {"from": "Владивосток", "to": TRANSPORT_STOP.get(area, area),
                                                           "date": dates[0].isoformat()}))
            if calls:
                return reply(calls)

        route = (results.get("build_route") or [{}])[-1]
        if step == 2 and mode == "car" and route.get("route_id") and (route.get("distance_km") or 0) > 150 \
                and "find_fuel_stations" not in results:
            return reply([_call(5, "find_fuel_stations", {"route_id": route["route_id"], "date": dates[0].isoformat()})])

        # Сборка плана.
        trips = (results.get("public_transport") or [{}])[-1].get("trips", [])
        trip_there = next((t for t in trips if t["trip_id"].endswith(":there") and t["departures"]
                           and (mode != "train" or t["type"] == "train")), None) or \
            next((t for t in trips if t["trip_id"].endswith(":there") and t["departures"]), None)
        trip_back = next((t for t in trips if trip_there and t["trip_id"] == trip_there["trip_id"].replace(":there", ":back")), None)
        lodgings = results.get("find_lodging") or []
        food_places = list((results.get("find_food") or [{}])[-1].get("places", []))

        def food_item(time_s: str, near: dict) -> dict:
            if food_places:
                f = food_places.pop(0)
                return {"time": time_s, "type": "food", "name": f["name"], "lat": f["lat"], "lon": f["lon"],
                        "url": f.get("url") or "", "details": f"Кухня: {f.get('cuisine') or 'смешанная'}."}
            return {"time": time_s, "type": "food", "name": "Кафе рядом", "lat": near["lat"], "lon": near["lon"],
                    "details": "Выберите заведение по ссылке на карте."}
        days_out = []
        for i, d in enumerate(dates):
            items, clock = [], 9 * 60.0
            if i == 0 and trip_there:
                dep = next((x for x in trip_there["departures"] if ":" in x and x[:2].isdigit() and int(x[:2]) >= 7),
                           trip_there["departures"][0])
                items.append({"time": dep, "type": "transfer", "name": f"Выезд из Владивостока ({ {'bus': 'автобус', 'train': 'электричка', 'ferry': 'паром'}.get(trip_there['type'], '')})",
                              "trip_id": trip_there["trip_id"], "lat": VL[0], "lon": VL[1],
                              "details": f"В пути ~{trip_there['duration_min'] // 60} ч {trip_there['duration_min'] % 60} мин."})
                if dep[:2].isdigit():
                    clock = int(dep[:2]) * 60 + int(dep[3:5]) + trip_there["duration_min"] + 20
            elif i == 0 and route_mode == "car" and area != "Владивосток":
                clock = 8 * 60
                items.append({"time": _hm(clock), "type": "transfer", "name": "Выезд из Владивостока", "lat": VL[0], "lon": VL[1],
                              "details": f"Дорога ~{route.get('duration_h', '?')} ч по маршруту."})
                clock += min(float(route.get("duration_h") or 2) * 60 * 0.6, 240)
            sunset = weather_days.get(d.isoformat(), {}).get("sunset") or "18:00"
            sunset_min = int(sunset[:2]) * 60 + int(sunset[3:5])
            for p in per_day[i]:
                if p["outdoor"] and clock + p["visit_h"] * 60 > sunset_min:
                    continue  # в темноте на природу не ведём
                hours = p.get("hours")
                if hours:
                    clock = max(clock, int(hours["open"][:2]) * 60)
                items.append({"time": _hm(clock), "type": "place", "name": p["name"], "place_id": p["id"],
                              "lat": p["lat"], "lon": p["lon"], "details": p["desc"].split(".")[0] + "."})
                clock += p["visit_h"] * 60 + 40
                if len(items) == 2:
                    items.append(food_item(_hm(clock), p))
                    clock += 60
            if i == len(dates) - 1 and trip_back and trip_back["departures"]:
                deps = [x for x in trip_back["departures"] if x[:2].isdigit()]
                dep = next((x for x in deps if int(x[:2]) * 60 + int(x[3:5]) >= clock), deps[-1] if deps else None)
                if dep:
                    items.append({"time": dep, "type": "transfer", "name": "Обратно во Владивосток",
                                  "trip_id": trip_back["trip_id"], "details": f"Последний рейс — {trip_back['last_departure']}."})
            day = {"date": d.isoformat(), "title": f"День {i + 1}: {area}", "items": items}
            if i < len(dates) - 1 and i < len(lodgings):
                opt = next((o for o in lodgings[i].get("options", []) if o.get("free", o.get("available"))), None)
                if opt:
                    day["lodging"] = {"name": opt["name"], "lodging_id": opt["id"], "lat": opt["lat"], "lon": opt["lon"],
                                      "price_rub": opt["price_rub"]}
            days_out.append(day)

        cautions = []
        risky = [f"{k[8:10]}.{k[5:7]}: {', '.join(v['risks'])}" for k, v in weather_days.items() if v.get("risks")]
        cautions.append("Погода: " + ("; ".join(risky) + " — возьмите дождевик." if risky else "без опасных осадков, но в сопках ветрено."))
        closed = [p for p in places if any(not is_open(p, d) for d in dates)]
        if closed:
            cautions.append(f"Выходной день у: {', '.join(p['name'] for p in closed[:2])} — в план не включены.")
        fuel = (results.get("find_fuel_stations") or [{}])[-1]
        if fuel:
            cautions.append(f"АЗС с {fuel.get('fuel', 'АИ-95')} по пути: {fuel.get('with_fuel', fuel.get('stations_with_fuel'))}, "
                            f"самый длинный перегон {fuel.get('max_gap_km')} км.")
        if trip_back:
            cautions.append(f"Последний рейс обратно — {trip_back['last_departure']}.")
        plan = {
            "title": f"{area}: {'выходные' if it.weekend else f'{n_days} дн.'} {'с ночёвкой' if n_days > 1 else ''}".strip(),
            "zachin": "Привет! Вот план поездки — всё проверил по погоде, расписаниям и режиму работы.",
            "summary": f"Маршрут по направлению «{area}» на {n_days} дн. {MODE_RU.get(mode, '')} с учётом погоды и режима работы мест.",
            "transport": mode if mode in ("car", "bike", "foot", "bus", "train") else "car",
            "start_date": dates[0].isoformat(), "end_date": dates[-1].isoformat(),
            "days": days_out,
            "weather_notes": [f"{v['date']}: {v.get('sky', v.get('summary', ''))}, {v.get('t', '')}" for v in weather_days.values()],
            "cautions": cautions,
        }
        return LLMResponse({"role": "assistant", "content": "", "tool_calls": [_call(99, "submit_plan", {"plan": plan})]},
                           usage, self.model)
