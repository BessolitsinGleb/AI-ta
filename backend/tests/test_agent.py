import json
from datetime import date

import pytest

from app.agent import run_agent
from app.demo_llm import DemoLLM
from app.llm import LLMError
from tests.helpers import ExplodingLLM, ScriptedLLM, call

WED = date(2026, 10, 21)
SAT = "2026-10-24"

GOOD_PLAN = {"title": "Владивосток", "zachin": "Гой еси!", "summary": "День в городе", "transport": "car",
             "cautions": ["Возможен дождь — зонт"], "days": [{"date": SAT, "items": [
                 {"time": "11:00", "type": "place", "name": "С-56", "place_id": "vl_s56", "lat": 43.115, "lon": 131.889}]}]}
BAD_PLAN = {**GOOD_PLAN, "days": [GOOD_PLAN["days"][0], {**GOOD_PLAN["days"][0], "date": "2026-10-25"}]}


@pytest.mark.asyncio
async def test_agent_loop_calls_tools_then_submits():
    llm = ScriptedLLM([
        [call("search_places", {"area": "Владивосток", "start_date": SAT}), call("get_weather", {"lat": 43.115, "lon": 131.889, "start_date": SAT}, 1)],
        [call("submit_plan", {"plan": GOOD_PLAN})],
    ])
    events = []

    async def on_event(ev):
        events.append(ev["type"])

    r = await run_agent("В субботу по Владивостоку на машине на день", "v2", llm=llm, today=WED, on_event=on_event, offline=True)
    assert r["status"] == "plan", r
    assert r["metrics"]["tools_called"] == ["search_places", "get_weather", "submit_plan"]
    assert r["metrics"]["llm_calls"] == 2 and r["metrics"]["total_tokens"] == 240
    assert r["check_summary"]["converges"], r["checks"]
    assert r["map"]["days"][0]["markers"]
    # Ответы тулов вернулись агенту как role=tool с нужными id.
    second = llm.seen[1]
    tool_msgs = [m for m in second if m["role"] == "tool"]
    assert {m["tool_call_id"] for m in tool_msgs} == {"c_search_places_0", "c_get_weather_1"}
    assert "Подводная" in tool_msgs[0]["content"] or "С-56" in tool_msgs[0]["content"]  # компактный JSON без \\u-эскейпов
    assert {"start", "tool", "tool_result", "check", "done"} <= set(events)


@pytest.mark.asyncio
async def test_repair_loop_fixes_contradiction():
    def fixed(messages):
        last = json.loads(messages[-1]["content"])
        assert last["accepted"] is False and any("не больше 1" in e for e in last["errors"])
        return [call("submit_plan", {"plan": GOOD_PLAN}, 2)]

    llm = ScriptedLLM([[call("submit_plan", {"plan": BAD_PLAN})], fixed])
    r = await run_agent("В субботу на машине на один день по Владивостоку", "v2", llm=llm, today=WED, offline=True)
    assert r["status"] == "plan" and len(r["plan"]["days"]) == 1
    assert r["metrics"]["tools_called"].count("submit_plan") == 2


@pytest.mark.asyncio
async def test_baseline_accepts_plan_without_repair():
    llm = ScriptedLLM([[call("submit_plan", {"plan": BAD_PLAN})]])
    r = await run_agent("В субботу на машине на один день", "v1", llm=llm, today=WED, offline=True)
    assert r["status"] == "plan" and not r["check_summary"]["converges"]


@pytest.mark.asyncio
async def test_prefilter_declines_without_llm():
    r = await run_agent("Реши мне задачу по алгебре", "v2", llm=ExplodingLLM(), today=WED, offline=True)
    assert r["status"] == "declined" and r["refusal"]["by"] == "prefilter"
    assert r["metrics"]["total_tokens"] == 0


@pytest.mark.asyncio
async def test_llm_decline_in_baseline():
    llm = ScriptedLLM([[call("decline_request", {"category": "other_region", "message": "Не Приморье"})]])
    r = await run_agent("Спланируй неделю в Сочи", "v1", llm=llm, today=WED, offline=True)
    assert r["status"] == "declined" and r["refusal"]["by"] == "llm" and r["refusal"]["category"] == "other_region"


@pytest.mark.asyncio
async def test_text_answer_gets_nudged_once():
    llm = ScriptedLLM(["Вот ваш план: …", [call("submit_plan", {"plan": GOOD_PLAN})]])
    r = await run_agent("В субботу по Владивостоку", "v2", llm=llm, today=WED, offline=True)
    assert r["status"] == "plan"
    assert llm.seen[1][-1]["role"] == "user" and "submit_plan" in llm.seen[1][-1]["content"]


@pytest.mark.asyncio
async def test_text_answer_in_baseline_is_returned():
    r = await run_agent("В субботу по Владивостоку", "v1", llm=ScriptedLLM(["просто текст"]), today=WED, offline=True)
    assert r["status"] == "text" and r["text"] == "просто текст"


@pytest.mark.asyncio
async def test_bad_tool_calls_do_not_crash():
    bad = {"id": "x1", "type": "function", "function": {"name": "search_places", "arguments": "{not json"}}
    llm = ScriptedLLM([[bad, call("teleport", {}, 1)], [call("submit_plan", {"plan": json.dumps(GOOD_PLAN)})]])
    r = await run_agent("В субботу на машине по Владивостоку", "v2", llm=llm, today=WED, offline=True)
    assert r["status"] == "plan"  # план строкой тоже принимается
    contents = [m["content"] for m in llm.seen[1] if m["role"] == "tool"]
    assert any("невалидный JSON" in c for c in contents) and any("нет такого тула" in c for c in contents)


@pytest.mark.asyncio
async def test_max_steps_limit():
    llm = ScriptedLLM([[call("search_places", {"area": "Находка"}, i)] for i in range(20)])
    r = await run_agent("В субботу в Находку", "v1", llm=llm, today=WED, offline=True)
    assert r["status"] == "error" and "шагов" in r["error"]


@pytest.mark.asyncio
async def test_llm_error_is_reported():
    class Broken:
        model = "x"

        async def chat(self, m, t):
            raise LLMError("OpenRouter 401: invalid key")

    r = await run_agent("В субботу в Находку", "v2", llm=Broken(), today=WED, offline=True)
    assert r["status"] == "error" and "401" in r["error"]


@pytest.mark.asyncio
async def test_no_key_falls_back_to_demo_planner():
    r = await run_agent("В субботу на автобусе в Находку на один день", "v2", today=WED, offline=True)
    assert r["status"] == "plan" and r["model"] == DemoLLM.model
    assert r["check_summary"]["converges"], r["checks"]


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    "Хочу на эти выходные поездить по Приморью на машине с ночёвкой, не больше двух дней",
    "На 3 дня на машине в Хасанский район с ночёвкой",
    "Велопрогулка по острову Русский завтра",
    "Пешком по Владивостоку в понедельник — история",
])
async def test_demo_end_to_end_plans_converge(query):
    r = await run_agent(query, "v2", llm=DemoLLM(), today=WED, offline=True)
    assert r["status"] == "plan"
    assert r["check_summary"]["errors"] == 0, [c for c in r["checks"] if not c["ok"]]
