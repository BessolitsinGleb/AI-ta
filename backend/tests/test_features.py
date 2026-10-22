"""Доработки: уточняющие вопросы, ссылки, еда из OSM, полная геометрия маршрута для карты."""
from datetime import date

import httpx
import pytest
import respx

from app.agent import attach_links, run_agent
from app.demo_llm import DemoLLM
from app.tools import ALL_TOOLS
from app.tools.base import ToolContext
from tests.helpers import ScriptedLLM, call
from tests.test_agent import GOOD_PLAN

WED = date(2026, 10, 21)
ASK = call("ask_user", {"questions": [{"text": "Какая кухня?", "options": ["Морепродукты", "Корейская", "Неважно"]}]})


@pytest.mark.asyncio
async def test_agent_asks_once_then_plans_with_answers():
    r = await run_agent("В субботу по Владивостоку, хочу вкусно поесть", "v2", llm=ScriptedLLM([[ASK]]), today=WED, offline=True)
    assert r["status"] == "question" and r["questions"][0]["options"][0] == "Морепродукты"

    llm = ScriptedLLM([[ASK], [call("submit_plan", {"plan": GOOD_PLAN})]])
    r = await run_agent("В субботу по Владивостоку", "v2", llm=llm, today=WED, offline=True,
                        answers=[{"question": "Какая кухня?", "answer": "Морепродукты"}])
    assert r["status"] == "plan"  # повторный вопрос игнорируется
    assert "Морепродукты" in llm.seen[0][1]["content"]


@pytest.mark.asyncio
async def test_skip_questions_and_eval_mode_hide_ask_tool():
    seen_tools = []

    class Spy(ScriptedLLM):
        async def chat(self, messages, tools):
            seen_tools.append({t["function"]["name"] for t in tools})
            return await super().chat(messages, tools)

    for kw in ({"answers": []}, {"allow_questions": False}):
        await run_agent("В субботу по Владивостоку", "v2", llm=Spy([[call("submit_plan", {"plan": GOOD_PLAN})]]), today=WED, offline=True, **kw)
    assert all("ask_user" not in s for s in seen_tools)


def test_links_for_places_food_trips_and_lodging():
    plan = {"days": [{"date": "2026-10-24", "items": [
        {"type": "place", "name": "С-56", "place_id": "vl_s56"},
        {"type": "food", "name": "Tsunami", "lat": 43.1, "lon": 131.9, "url": "https://example.org"},
        {"type": "transfer", "name": "Автобус", "trip_id": "bus_vl_nk:back"},
    ], "lodging": {"name": "Отель", "lat": 42.8, "lon": 132.9}}]}
    attach_links(plan)
    items = plan["days"][0]["items"]
    assert "yandex.ru/maps" in items[0]["links"][0]["url"] and "131.88900" in items[0]["links"][0]["url"]
    assert items[1]["links"][0] == {"title": "Сайт", "url": "https://example.org"}
    rasp = items[2]["links"][0]["url"]
    assert rasp.startswith("https://rasp.yandex.ru/search/bus/") and "when=2026-10-24" in rasp
    assert rasp.index("fromName=%D0%9D") < rasp.index("toName")  # обратный рейс: из Находки
    assert "гостиницы" in httpx.URL(plan["days"][0]["lodging"]["links"][0]["url"]).params["text"]


@pytest.mark.asyncio
@respx.mock
async def test_find_food_real_places_and_cuisine_match():
    respx.get("https://nominatim.openstreetmap.org/search").mock(return_value=httpx.Response(200, json=[
        {"name": "Tsunami", "lat": "43.11", "lon": "131.88", "extratags": {"cuisine": "seafood", "website": "https://t.ru"}},
        {"name": "Пицца", "lat": "43.12", "lon": "131.89", "extratags": {"cuisine": "pizza"}},
    ]))
    respx.get("https://t.ru").mock(return_value=httpx.Response(200))  # сайт заведения открывается
    full, visible = await ALL_TOOLS["find_food"].run({"near_lat": 43.115, "near_lon": 131.885, "cuisine": "морепродукты"},
                                                     ToolContext(today=WED, offline=False))
    assert full["places"][0]["name"] == "Tsunami" and full["places"][0]["match"]
    assert visible["places"][0]["cuisine"] == "морепродукты" and visible["places"][0]["url"] == "https://t.ru"


@pytest.mark.asyncio
async def test_find_food_offline_gives_search_link():
    full, _ = await ALL_TOOLS["find_food"].run({"area": "Находка"}, ToolContext(today=WED, offline=True))
    assert full["places"] == [] and full["search_url"].startswith("https://yandex.ru/maps/")


@pytest.mark.asyncio
@respx.mock
async def test_map_uses_full_geometry():
    route = respx.get(url__startswith="https://routing.openstreetmap.de/routed-foot/").mock(return_value=httpx.Response(200, json={
        "code": "Ok", "routes": [{"distance": 1000, "duration": 900, "geometry": {"coordinates": [[131.88, 43.11], [131.89, 43.12]]},
                                  "legs": [{"distance": 1000, "duration": 900}]}]}))
    ctx = ToolContext(today=WED, offline=False)
    await ALL_TOOLS["build_route"].run({"mode": "foot", "points": [{"lat": 43.11, "lon": 131.88}, {"lat": 43.12, "lon": 131.89}],
                                        "_full_geometry": True}, ctx)
    assert route.calls.last.request.url.params["overview"] == "full"


@pytest.mark.asyncio
async def test_demo_asks_about_cuisine_and_uses_answer():
    r = await run_agent("В субботу по Владивостоку на машине, хочу вкусно поесть", "v2", llm=DemoLLM(), today=WED, offline=True)
    assert r["status"] == "question"
    r = await run_agent("В субботу по Владивостоку на машине, хочу вкусно поесть", "v2", llm=DemoLLM(), today=WED, offline=True,
                        answers=[{"question": "Какую кухню предпочитаете?", "answer": "Морепродукты"}])
    assert r["status"] == "plan"
    food = [i for d in r["plan"]["days"] for i in d["items"] if i["type"] == "food"]
    assert food and all(i.get("links") for i in food)


def test_dataset_places_get_coordinates_for_map():
    from app.agent import fill_coords
    from app.tools.places import get_place

    plan = {"days": [{"items": [{"type": "place", "name": "Подлодка", "place_id": "vl_s56"}, {"type": "note", "name": "Отдых"}]}]}
    fill_coords(plan)
    place, note = plan["days"][0]["items"]
    assert (place["lat"], place["lon"]) == (get_place("vl_s56")["lat"], get_place("vl_s56")["lon"]) and "lat" not in note


def test_ip_limits_scale_behind_nat(monkeypatch):
    from dataclasses import replace

    from fastapi import HTTPException
    from starlette.requests import Request

    from app import ratelimit
    req = Request({"type": "http", "client": ("151.101.128.223", 1), "headers": []})
    monkeypatch.setattr(ratelimit, "settings", replace(ratelimit.settings, ip_limit_scale=3))
    for _ in range(15):  # 5 × 3 — за общим NAT зал не упирается в лимит одного человека
        ratelimit.check_ip(req, "register", 5, 3600)
    with pytest.raises(HTTPException):
        ratelimit.check_ip(req, "register", 5, 3600)

