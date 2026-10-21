"""Метрики эвала: качество (выбор тулов + попадание в интент), стоимость (токены, $) и скорость."""
from __future__ import annotations

import statistics
from typing import Any

DATA_TOOLS = {"geocode", "search_places", "get_weather", "build_route", "find_fuel_stations", "find_lodging",
              "public_transport", "find_events", "place_info"}


def score_run(case: dict, result: dict) -> dict:
    exp = case["expect"]
    status = result.get("status")
    called = set(result.get("metrics", {}).get("tools_called", [])) & DATA_TOOLS
    row: dict[str, Any] = {
        "id": case["id"], "query": case["query"], "status": status,
        "tokens": result.get("metrics", {}).get("total_tokens", 0),
        "cost_usd": result.get("metrics", {}).get("cost_usd", 0.0),
        "latency_s": result.get("metrics", {}).get("latency_s", 0.0),
        "llm_calls": result.get("metrics", {}).get("llm_calls", 0),
        "tools_called": sorted(called),
    }
    if exp.get("decline"):
        declined = status == "declined"
        row["tool_ok"] = declined and not called  # «правильный тул» для нецелевого запроса — отказ без сбора данных
        row["tool_recall"] = 1.0 if declined else 0.0
        row["intent_score"] = 1.0 if declined else 0.0
        row["converges"] = None
        row["category_ok"] = declined and (result.get("refusal") or {}).get("category") == exp.get("category")
    else:
        required = set(exp.get("tools", []))
        recall = len(required & called) / len(required) if required else 1.0
        row["tool_recall"] = round(recall, 3)
        row["tool_ok"] = status == "plan" and recall == 1.0
        if status == "plan":
            summ = result.get("check_summary") or {}
            row["intent_score"] = float(summ.get("score", 0.0))
            row["converges"] = bool(summ.get("converges"))
            row["failed_checks"] = [c["text"] for c in result.get("checks", []) if not c["ok"]]
        else:
            row["intent_score"] = 0.0
            row["converges"] = False
            row["failed_checks"] = [result.get("error") or result.get("text") or status]
        row["category_ok"] = None
    row["quality"] = round(0.5 * float(row["tool_ok"]) + 0.5 * row["intent_score"], 3)
    return row


def aggregate(rows: list[dict]) -> dict:
    def mean(key: str, pool: list[dict] | None = None) -> float:
        vals = [float(r[key]) for r in (pool or rows) if r.get(key) is not None]
        return round(statistics.mean(vals), 3) if vals else 0.0

    plans = [r for r in rows if r["converges"] is not None]
    declines = [r for r in rows if r["converges"] is None]
    lat = sorted(r["latency_s"] for r in rows)
    return {
        "n": len(rows),
        "quality": mean("quality"),
        "tool_accuracy": mean("tool_ok"),
        "tool_recall": mean("tool_recall"),
        "intent_score": mean("intent_score", plans) if plans else 0.0,
        "converge_rate": round(sum(1 for r in plans if r["converges"]) / len(plans), 3) if plans else 0.0,
        "guardrail_accuracy": round(sum(1 for r in declines if r["status"] == "declined") / len(declines), 3) if declines else 0.0,
        "errors": sum(1 for r in rows if r["status"] == "error"),
        "tokens_avg": round(statistics.mean(r["tokens"] for r in rows)) if rows else 0,
        "tokens_avg_plan": round(statistics.mean(r["tokens"] for r in plans)) if plans else 0,
        "cost_usd_total": round(sum(r["cost_usd"] for r in rows), 4),
        "cost_usd_avg": round(sum(r["cost_usd"] for r in rows) / len(rows), 5) if rows else 0.0,
        "latency_avg_s": round(statistics.mean(lat), 2) if lat else 0.0,
        "latency_p50_s": round(statistics.median(lat), 2) if lat else 0.0,
        "latency_max_s": round(max(lat), 2) if lat else 0.0,
    }


def markdown_table(summaries: list[dict]) -> str:
    head = ("| Вариант | Модель | Качество | Тул верный | Интент (сверка) | План сходится | Guardrails | "
            "Токены / запрос | $ / запрос | Время, с (ср / p50) |\n|---|---|---|---|---|---|---|---|---|---|\n")
    lines = []
    for s in summaries:
        a = s["aggregate"]
        lines.append(
            f"| {s['version']} · {s['label']} | `{s['model']}` | **{a['quality']:.2f}** | {a['tool_accuracy']:.0%} | "
            f"{a['intent_score']:.2f} | {a['converge_rate']:.0%} | {a['guardrail_accuracy']:.0%} | {a['tokens_avg']:,} | "
            f"{a['cost_usd_avg']:.4f} | {a['latency_avg_s']} / {a['latency_p50_s']} |".replace(",", " ")
        )
    return head + "\n".join(lines) + "\n"
