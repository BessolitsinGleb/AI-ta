"""Прогон эвала: python eval/run_eval.py --versions v1 v2 v3 [--limit N] [--concurrency 3]

Пишет eval/results/<версия>.json (построчно) и eval/results/summary.md (сравнительная таблица).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent import run_agent, today_local, versions  # noqa: E402
from app.evaluation import aggregate, markdown_table, score_run  # noqa: E402
from app.config import settings  # noqa: E402

RESULTS = ROOT / "eval" / "results"


async def run_version(version: str, cases: list[dict], concurrency: int, demo: bool) -> dict:
    sem = asyncio.Semaphore(concurrency)
    rows: list[dict] = [None] * len(cases)  # type: ignore[list-item]

    async def one(i: int, case: dict) -> None:
        async with sem:
            llm = None
            if demo:
                from app.demo_llm import DemoLLM
                llm = DemoLLM()
            result = await run_agent(case["query"], version, llm=llm, allow_questions=False)
            rows[i] = score_run(case, result)
            r = rows[i]
            print(f"  [{version}] {case['id']} {r['status']:<8} q={r['quality']:.2f} tools={'✓' if r['tool_ok'] else '✗'} "
                  f"tok={r['tokens']:>6} {r['latency_s']:>5}s  {case['query'][:48]}", flush=True)

    await asyncio.gather(*(one(i, c) for i, c in enumerate(cases)))
    ver = versions()[version]
    return {"version": version, "label": ver.label, "model": "demo/rule-based-planner" if demo else ver.model,
            "aggregate": aggregate(rows), "rows": rows}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", nargs="+", default=["v1", "v2", "v3"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", nargs="+", default=None, help="прогнать только эти запросы, например q01 q02")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--demo", action="store_true", help="без LLM: детерминированный планировщик (проверка обвязки)")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    if not settings.openrouter_api_key and not args.demo:
        sys.exit("Нет OPENROUTER_API_KEY в .env — добавьте ключ или запустите с --demo")
    cases = json.loads((ROOT / "eval" / "queries.json").read_text(encoding="utf-8"))
    if args.ids:
        cases = [c for c in cases if c["id"] in set(args.ids)]
    if args.limit:
        cases = cases[: args.limit]
    RESULTS.mkdir(parents=True, exist_ok=True)
    summaries = []
    t0 = time.time()
    for v in args.versions:
        print(f"== {v}: {versions()[v].label} ({versions()[v].model})", flush=True)
        s = await run_version(v, cases, args.concurrency, args.demo)
        s["date"] = today_local().isoformat()
        suffix = f"_{args.tag}" if args.tag else ("_demo" if args.demo else "")
        (RESULTS / f"{v}{suffix}.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
        summaries.append(s)
        print("   ", json.dumps(s["aggregate"], ensure_ascii=False), flush=True)
    table = markdown_table(summaries)
    header = (f"# Эвал: {len(cases)} запросов, {datetime.now():%Y-%m-%d %H:%M}\n\n"
              f"Качество = 0,5 × «верный тул» + 0,5 × доля пройденных проверок сверки плана "
              f"(для нецелевых запросов — корректный отказ).\n\n")
    name = "summary_demo.md" if args.demo else f"summary{('_' + args.tag) if args.tag else ''}.md"
    (RESULTS / name).write_text(header + table, encoding="utf-8")
    print("\n" + table)
    print(f"Готово за {time.time() - t0:.0f} с → {RESULTS / name}")


if __name__ == "__main__":
    asyncio.run(main())
