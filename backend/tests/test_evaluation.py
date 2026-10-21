from app.evaluation import aggregate, markdown_table, score_run

PLAN_CASE = {"id": "q", "query": "…", "expect": {"decline": False, "tools": ["search_places", "get_weather"]}}
DECLINE_CASE = {"id": "d", "query": "…", "expect": {"decline": True, "category": "off_topic"}}


def result(status, tools, score=1.0, converges=True, **kw):
    return {"status": status, "metrics": {"tools_called": tools, "total_tokens": 1000, "cost_usd": 0.001, "latency_s": 3.0},
            "check_summary": {"score": score, "converges": converges}, "checks": [], **kw}


def test_plan_scoring():
    row = score_run(PLAN_CASE, result("plan", ["search_places", "get_weather", "submit_plan"], 0.8, False))
    assert row["tool_ok"] and row["intent_score"] == 0.8 and row["quality"] == 0.9
    miss = score_run(PLAN_CASE, result("plan", ["search_places", "submit_plan"]))
    assert not miss["tool_ok"] and miss["tool_recall"] == 0.5


def test_decline_scoring():
    good = score_run(DECLINE_CASE, result("declined", [], refusal={"category": "off_topic"}))
    assert good["tool_ok"] and good["quality"] == 1.0 and good["category_ok"]
    bad = score_run(DECLINE_CASE, result("plan", ["search_places", "submit_plan"]))
    assert not bad["tool_ok"] and bad["quality"] == 0.0


def test_aggregate_and_table():
    rows = [score_run(PLAN_CASE, result("plan", ["search_places", "get_weather"])),
            score_run(DECLINE_CASE, result("declined", [], refusal={"category": "off_topic"}))]
    a = aggregate(rows)
    assert a["n"] == 2 and a["tool_accuracy"] == 1.0 and a["guardrail_accuracy"] == 1.0 and a["converge_rate"] == 1.0
    table = markdown_table([{"version": "v1", "label": "Бейзлайн", "model": "m", "aggregate": a}])
    assert "| v1 · Бейзлайн |" in table
