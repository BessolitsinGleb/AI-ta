from datetime import date

import httpx
import pytest
import respx

from app.tools import ALL_TOOLS
from app.tools.base import ToolContext
from app.tools.fuel import station_info

WED = date(2026, 10, 21)


def online():
    return ToolContext(today=WED, offline=False, compact=True)


def offline(compact=True):
    return ToolContext(today=WED, offline=True, compact=compact)


async def run(name, args, ctx):
    return await ALL_TOOLS[name].run(args, ctx)


def test_registry_schemas_are_valid():
    for tool in ALL_TOOLS.values():
        s = tool.schema()
        assert s["type"] == "function" and s["function"]["parameters"]["type"] == "object"
        assert tool.description


@pytest.mark.asyncio
async def test_search_places_marks_closed_days():
    full, visible = await run("search_places", {"area": "Владивосток", "interests": ["музей"],
                                                "start_date": "2026-10-26", "end_date": "2026-10-26"}, offline())
    arseniev = next(p for p in full["places"] if p["id"] == "vl_arseniev")
    assert arseniev["open_on"]["2026-10-26"] is False
    compact = next(p for p in visible["places"] if p["id"] == "vl_arseniev")
    assert compact["closed_on"] == ["2026-10-26"]
    assert "desc" not in compact  # сжатие контекста


@pytest.mark.asyncio
async def test_search_places_district():
    full, _ = await run("search_places", {"area": "Хасанский район", "limit": 10}, offline())
    assert full["count"] >= 4
    assert all("Хасан" in p["area"] for p in full["places"])


@pytest.mark.asyncio
@respx.mock
async def test_weather_open_meteo_parsing_and_risks():
    respx.get("https://api.open-meteo.com/v1/forecast").mock(return_value=httpx.Response(200, json={"daily": {
        "time": ["2026-10-24", "2026-10-25"], "weather_code": [65, 1], "temperature_2m_max": [11, 14],
        "temperature_2m_min": [6, 4], "precipitation_sum": [18.2, 0], "precipitation_probability_max": [90, 5],
        "wind_speed_10m_max": [12.5, 3], "sunrise": ["2026-10-24T07:10", "2026-10-25T07:11"],
        "sunset": ["2026-10-24T18:12", "2026-10-25T18:10"]}}))
    ctx = online()
    full, visible = await run("get_weather", {"lat": 43.1, "lon": 131.9, "start_date": "2026-10-24", "end_date": "2026-10-25"}, ctx)
    assert full["source"] == "open-meteo"
    assert full["days"][0]["risks"] == ["дождь", "сильный ветер"]
    assert full["days"][0]["sunset"] == "18:12"
    assert visible["days"][1].get("risks") is None
    assert "Open-Meteo" in ctx.sources and ctx.weather["43.10,131.90"]["2026-10-24"]["summary"] == "ливень"


@pytest.mark.asyncio
@respx.mock
async def test_weather_falls_back_when_api_down():
    respx.get("https://api.open-meteo.com/v1/forecast").mock(return_value=httpx.Response(503))
    full, _ = await run("get_weather", {"lat": 43.1, "lon": 131.9, "start_date": "2026-10-24"}, online())
    assert full["source"] == "offline" and "недоступен" in full["note"]


@pytest.mark.asyncio
async def test_weather_beyond_horizon():
    full, _ = await run("get_weather", {"lat": 43.1, "lon": 131.9, "start_date": "2026-12-30"}, offline())
    assert full["days"] == [] and "прогноз доступен" in full["note"]


@pytest.mark.asyncio
@respx.mock
async def test_route_osrm_and_geometry_hidden_from_llm():
    respx.get(url__startswith="https://router.project-osrm.org/route/v1/driving/").mock(return_value=httpx.Response(200, json={
        "code": "Ok", "routes": [{"distance": 186000, "duration": 9900, "geometry": {"coordinates": [[131.88, 43.11], [132.5, 43.0], [132.87, 42.81]]},
                                  "legs": [{"distance": 186000, "duration": 9900}]}]}))
    ctx = online()
    pts = [{"name": "Владивосток", "lat": 43.11, "lon": 131.88}, {"name": "Находка", "lat": 42.81, "lon": 132.87}]
    full, visible = await run("build_route", {"mode": "car", "points": pts}, ctx)
    assert full["distance_km"] == 186.0 and full["source"] == "osrm"
    assert "geometry" not in visible and visible["route_id"] in ctx.routes


@pytest.mark.asyncio
async def test_route_fallback_and_bike_limit_warning():
    pts = [{"lat": 43.11, "lon": 131.88}, {"lat": 42.81, "lon": 132.87}]
    full, _ = await run("build_route", {"mode": "bike", "points": pts}, offline())
    assert full["source"] == "estimate" and "warning" in full


@pytest.mark.asyncio
async def test_route_needs_two_points():
    full, _ = await run("build_route", {"mode": "car", "points": [{"lat": 1, "lon": 2}]}, offline())
    assert "error" in full


@pytest.mark.asyncio
async def test_fuel_along_route_offline():
    ctx = offline()
    pts = [{"lat": 43.1155, "lon": 131.8855}, {"lat": 43.32, "lon": 132.36}, {"lat": 43.13, "lon": 133.12}]
    route, _ = await run("build_route", {"mode": "car", "points": pts}, ctx)
    full, visible = await run("find_fuel_stations", {"route_id": route["route_id"], "date": "2026-10-24"}, ctx)
    assert full["stations"] and full["max_gap_km"] < route["distance_km"]
    assert [s["km_from_start"] for s in full["stations"]] == sorted(s["km_from_start"] for s in full["stations"])
    assert visible["with_fuel"] == full["stations_with_fuel"]
    assert any(v is not None for st in full["stations"] for v in st["fuel"].values())  # из снимка OSM, не мок


@pytest.mark.asyncio
async def test_fuel_unknown_route():
    full, _ = await run("find_fuel_stations", {"route_id": "nope"}, offline())
    assert "error" in full


def test_fuel_station_from_osm_tags():
    st = station_info({"id": 7, "lat": 43.1, "lon": 131.9, "tags": {
        "brand": "Роснефть", "fuel:octane_92": "yes", "fuel:diesel": "no", "fuel:lpg": "yes", "opening_hours": "24/7",
        "shop": "convenience", "toilets": "yes", "payment:cards": "yes", "addr:street": "Снеговая улица", "addr:housenumber": "1"}})
    assert st["name"] == "Роснефть" and st["hours"] == "круглосуточно"
    assert st["fuel"] == {"АИ-92": True, "АИ-95": None, "ДТ": False, "Газ": True}  # не указано — None, а не выдумка
    assert {"магазин", "туалет", "оплата картой"} <= set(st["services"]) and st["address"] == "Снеговая улица 1"


@pytest.mark.asyncio
async def test_food_skips_places_with_dead_sites(monkeypatch):
    from app.tools import food

    async def nominatim(q, box, limit=10):
        return [{"name": "Бар-призрак", "lat": "43.1160", "lon": "131.8860", "extratags": {"website": "https://gone.example"}},
                {"name": "Живое кафе", "lat": "43.1170", "lon": "131.8870", "extratags": {"website": "https://alive.example"}},
                {"name": "Кафе без следов", "lat": "43.1150", "lon": "131.8850", "extratags": {}}]

    async def status(urls, parallel=6):
        return {u: u == "https://alive.example" for u in urls}

    monkeypatch.setattr(food, "_nominatim_raw", nominatim)
    monkeypatch.setattr(food, "check_many", status)
    full, visible = await run("find_food", {"near_lat": 43.1155, "near_lon": 131.8855}, online())
    names = [p["name"] for p in full["places"]]
    assert "Бар-призрак" not in names and names[0] == "Живое кафе"  # сайт открывается — первым
    assert next(p for p in visible["places"] if p["name"] == "Кафе без следов")["unverified"] is True


@pytest.mark.asyncio
async def test_transport_both_directions_and_weekdays():
    full, _ = await run("public_transport", {"from": "Владивосток", "to": "Находка", "date": "2026-10-24"}, offline())
    ids = {t["trip_id"] for t in full["trips"]}
    assert {"bus_vl_nk:there", "train_vl_nk:there"} <= ids
    tue, _ = await run("public_transport", {"from": "Владивосток", "to": "Находка", "date": "2026-10-27", "type": "train"}, offline())
    assert tue["trips"][0]["runs_on_date"] is False


@pytest.mark.asyncio
async def test_transport_unknown_stop():
    full, visible = await run("public_transport", {"from": "Владивосток", "to": "Москва", "date": "2026-10-24"}, offline())
    assert "error" in full and visible["known_stops"]


@pytest.mark.asyncio
async def test_lodging_near_point():
    full, visible = await run("find_lodging", {"area": "Находка", "date": "2026-10-24"}, offline())
    assert full["options"] and all(o["distance_km"] <= 70 for o in full["options"])
    assert len(visible["options"]) <= 4


@pytest.mark.asyncio
async def test_events_by_weekday():
    full, _ = await run("find_events", {"area": "Владивосток", "start_date": "2026-10-24", "end_date": "2026-10-25"}, offline())
    assert any("ярмарка" in e["title"].lower() for e in full["events"])


@pytest.mark.asyncio
@respx.mock
async def test_geocode_nominatim_then_fallback():
    route = respx.get("https://nominatim.openstreetmap.org/search")
    route.mock(return_value=httpx.Response(200, json=[{"lat": "42.82", "lon": "132.89", "display_name": "Находка"}]))
    full, _ = await run("geocode", {"query": "Находка"}, online())
    assert full["source"] == "nominatim"
    route.mock(return_value=httpx.Response(500))
    full, _ = await run("geocode", {"query": "Уссурийск"}, online())
    assert full["source"] == "gazetteer"


@pytest.mark.asyncio
@respx.mock
async def test_place_info_wikipedia():
    respx.get(url__startswith="https://ru.wikipedia.org/api/rest_v1/page/summary/").mock(
        return_value=httpx.Response(200, json={"title": "Находка", "extract": "Город в Приморском крае."}))
    full, visible = await run("place_info", {"title": "Находка"}, online())
    assert "Приморском" in full["extract"] and visible["title"] == "Находка"
