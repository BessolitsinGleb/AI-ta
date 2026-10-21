from datetime import date

import pytest

from app.intents import parse_intents
from app.tools.base import ToolContext
from app.validator import summarize, validate_plan

WED = date(2026, 10, 21)
MON = "2026-10-26"
SAT, SUN = "2026-10-24", "2026-10-25"


def ctx(**kw):
    return ToolContext(today=WED, offline=True, **kw)


def checks_by_id(checks):
    return {c.id: c for c in checks}


def place(pid, name, lat, lon, time="10:00"):
    return {"time": time, "type": "place", "name": name, "place_id": pid, "lat": lat, "lon": lon}


GOOD_ITEM = place("vl_s56", "Подлодка С-56", 43.1150, 131.8890, "11:00")


def sunny(c: ToolContext, dates, lat=43.115, lon=131.889):
    c.weather[f"{lat:.2f},{lon:.2f}"] = {d: {"date": d, "summary": "ясно", "tmin": 5, "tmax": 12, "precip_mm": 0,
                                             "wind_max_ms": 3, "sunset": "18:15", "risks": []} for d in dates}


@pytest.mark.asyncio
async def test_too_many_days_is_error():
    it = parse_intents("на выходные, не больше двух дней", WED)
    plan = {"transport": "car", "days": [{"date": d, "items": [GOOD_ITEM]} for d in (SAT, SUN, "2026-10-26")]}
    c = ctx()
    sunny(c, [SAT, SUN, MON])
    res = checks_by_id(await validate_plan(plan, it, c))
    assert not res["days_limit"].ok
    assert not res["dates"].ok


@pytest.mark.asyncio
async def test_closed_museum_on_monday():
    it = parse_intents("в понедельник по Владивостоку", WED)
    plan = {"transport": "foot", "days": [{"date": MON, "items": [place("vl_arseniev", "Музей Арсеньева", 43.1166, 131.8832)]}]}
    c = ctx()
    sunny(c, [MON], 43.1166, 131.8832)
    res = checks_by_id(await validate_plan(plan, it, c))
    assert not res["opening_hours"].ok and "выходной" in res["opening_hours"].text


@pytest.mark.asyncio
async def test_visit_outside_opening_hours():
    plan = {"transport": "car", "days": [{"date": SAT, "items": [place("vl_s56", "С-56", 43.1150, 131.8890, "21:00")]}]}
    c = ctx()
    sunny(c, [SAT])
    res = checks_by_id(await validate_plan(plan, parse_intents("в субботу", WED), c))
    assert not res["opening_hours"].ok


@pytest.mark.asyncio
async def test_bike_under_rain_is_error():
    it = parse_intents("на велосипеде в субботу", WED)
    plan = {"transport": "bike", "days": [{"date": SAT, "items": [place("vl_tokarevsky", "Маяк", 43.0745, 131.8425)]}]}
    c = ctx()
    c.weather["43.07,131.84"] = {SAT: {"date": SAT, "summary": "ливень", "tmin": 8, "tmax": 12, "precip_mm": 22,
                                      "wind_max_ms": 12, "sunset": "18:15", "risks": ["дождь", "сильный ветер"]}}
    res = checks_by_id(await validate_plan(plan, it, c))
    assert not res["weather"].ok and "велосипед" in res["weather"].text


@pytest.mark.asyncio
async def test_rain_acknowledged_by_car_traveller_is_ok():
    plan = {"transport": "car", "cautions": ["Возможен дождь — возьмите зонт"],
            "days": [{"date": SAT, "items": [place("vl_s56", "С-56", 43.1150, 131.8890, "11:00")]}]}
    c = ctx()
    c.weather["43.12,131.89"] = {SAT: {"date": SAT, "summary": "дождь", "tmin": 8, "tmax": 12, "precip_mm": 9,
                                      "wind_max_ms": 4, "sunset": "18:15", "risks": ["дождь"]}}
    res = checks_by_id(await validate_plan(plan, parse_intents("в субботу на машине", WED), c))
    assert res["weather"].ok


@pytest.mark.asyncio
async def test_outdoor_place_after_sunset():
    plan = {"transport": "car", "days": [{"date": SAT, "items": [place("vl_tobizina", "Мыс Тобизина", 42.962, 131.866, "17:00")]}]}
    c = ctx()
    sunny(c, [SAT], 42.962, 131.866)
    res = checks_by_id(await validate_plan(plan, parse_intents("в субботу", WED), c))
    assert not res["weather"].ok and "темно" in res["weather"].text


@pytest.mark.asyncio
async def test_long_car_trip_requires_fuel_check():
    it = parse_intents("на машине на выходные", WED)
    plan = {"transport": "car", "days": [
        {"date": SAT, "items": [GOOD_ITEM, place("hn_khanka", "Ханка", 44.765, 132.045, "15:00")]},
    ]}
    c = ctx()
    sunny(c, [SAT], 43.115, 131.889)
    sunny(c, [SAT], 44.765, 132.045)
    res = checks_by_id(await validate_plan(plan, it, c))
    assert not res["fuel"].ok
    c.fuel["r1"] = {"max_gap_km": 80}
    res = checks_by_id(await validate_plan(plan, it, c))
    assert res["fuel"].ok


@pytest.mark.asyncio
async def test_walking_distance_limit():
    it = parse_intents("пешком в субботу", WED)
    plan = {"transport": "foot", "days": [{"date": SAT, "items": [
        place("vl_s56", "С-56", 43.115, 131.889, "10:00"), place("nk_sestra", "Сестра", 42.798, 132.888, "14:00")]}]}
    c = ctx()
    sunny(c, [SAT], 42.798, 132.888)
    sunny(c, [SAT], 43.115, 131.889)
    res = checks_by_id(await validate_plan(plan, it, c))
    assert not res["distance_day1"].ok


@pytest.mark.asyncio
async def test_bus_schedule_checks():
    it = parse_intents("в субботу на автобусе в Лазо", WED)
    item = {"time": "07:30", "type": "transfer", "name": "Автобус", "trip_id": "bus_vl_lz:there"}
    plan = {"transport": "bus", "days": [{"date": SAT, "items": [item, place("lz_reserve", "Визит-центр", 43.388, 133.901, "15:00")]}]}
    c = ctx()
    sunny(c, [SAT], 43.388, 133.901)
    res = checks_by_id(await validate_plan(plan, it, c))
    assert res["schedule"].ok  # по субботам рейс ходит…
    assert not res["opening_hours"].ok  # …а визит-центр закрыт
    plan["days"][0]["date"] = "2026-10-27"  # вторник: рейс не ходит
    res = checks_by_id(await validate_plan(plan, parse_intents("во вторник на автобусе", WED), c))
    assert not res["schedule"].ok


@pytest.mark.asyncio
async def test_bus_without_trips_fails():
    plan = {"transport": "bus", "days": [{"date": SAT, "items": [GOOD_ITEM]}]}
    c = ctx()
    sunny(c, [SAT])
    res = checks_by_id(await validate_plan(plan, parse_intents("на автобусе в субботу", WED), c))
    assert not res["schedule"].ok


@pytest.mark.asyncio
async def test_overnight_requires_lodging_and_region():
    it = parse_intents("на выходные с ночёвкой", WED)
    plan = {"transport": "car", "days": [
        {"date": SAT, "items": [GOOD_ITEM]},
        {"date": SUN, "items": [{"time": "10:00", "type": "place", "name": "Сочи", "lat": 43.6, "lon": 39.7}]},
    ]}
    c = ctx()
    sunny(c, [SAT, SUN])
    res = checks_by_id(await validate_plan(plan, it, c))
    assert not res["overnight"].ok
    assert not res["region"].ok


@pytest.mark.asyncio
async def test_good_plan_converges():
    it = parse_intents("в субботу на машине по Владивостоку", WED)
    plan = {"transport": "car", "days": [{"date": SAT, "items": [
        GOOD_ITEM, {"time": "13:00", "type": "food", "name": "Обед"},
        place("vl_fortress", "Крепость", 43.1192, 131.8738, "14:30")]}]}
    c = ctx()
    sunny(c, [SAT], 43.115, 131.889)
    sunny(c, [SAT], 43.12, 131.87)
    checks = await validate_plan(plan, it, c)
    s = summarize(checks)
    assert s["converges"], [c.text for c in checks if not c.ok]
    assert s["score"] == 1.0


@pytest.mark.asyncio
async def test_empty_plan():
    checks = await validate_plan({"days": []}, parse_intents("", WED), ctx())
    assert summarize(checks)["errors"] == 1
