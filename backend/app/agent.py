"""Агентный цикл: LLM выбирает тул → тул вызывается → результат возвращается агенту → … → submit_plan.

Три версии пайплайна для эвала:
  v1 — бейзлайн: короткий промпт, сырые ответы тулов в контексте, без пред-фильтра и без цикла исправлений;
  v2 — подробный промпт, сжатие контекста, guardrail-пред-фильтр, сверка плана с повторной попыткой;
  v3 — пайплайн v2 на другой (лёгкой) модели.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Awaitable, Callable

from .config import TZ, settings
from .guardrails import precheck
from .intents import parse_intents
from .llm import ChatModel, LLMError, OpenRouterLLM, Usage
from .prompts import ASK_TOOL, FINISH_TOOLS, LAST_STEPS_NUDGE, REPAIR_NUDGE, TRUNCATED_NUDGE, baseline_prompt, full_prompt
from .tools import ALL_TOOLS, ToolContext
from .tools.routing import build_route
from .links import rasp, yandex_maps
from .tools.places import get_place
from .tools.transport import get_trip
from .validator import plan_transport, summarize, validate_plan

EventCb = Callable[[dict], Awaitable[None]]
DAY_COLORS = ["#f0641e", "#2e6b62", "#2f5d8a", "#8a5a00", "#6b3fa0", "#00796b", "#9c2f6b"]


@dataclass(frozen=True)
class AgentVersion:
    key: str
    label: str
    model: str
    compact: bool
    prefilter: bool
    repair: bool
    prompt: str  # baseline | full
    max_steps: int = 10
    max_repairs: int = 2


def versions() -> dict[str, AgentVersion]:
    return {
        "v1": AgentVersion("v1", "Бейзлайн", settings.model_v1, compact=False, prefilter=False, repair=False,
                           prompt="baseline", max_steps=10, max_repairs=0),
        "v2": AgentVersion("v2", "Сжатие контекста + сверка", settings.model_v2, compact=True, prefilter=True,
                           repair=True, prompt="full", max_steps=12),
        "v3": AgentVersion("v3", "Финальная: v2 + исправления + DeepSeek", settings.model_v3, compact=True, prefilter=True,
                           repair=True, prompt="full", max_steps=12),
    }


def today_local() -> date:
    return datetime.now(TZ).date()


def _dump(obj: Any, compact: bool) -> str:
    if compact:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)
    return json.dumps(obj, indent=2, default=str)  # бейзлайн: «как получилось» — ASCII-эскейпы и отступы


def _short(obj: Any, n: int = 160) -> str:
    s = json.dumps(obj, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[: n - 1] + "…"


def describe_tool(name: str, res: dict) -> str:
    """Человекочитаемая строка для «летописи трудов» в интерфейсе."""
    if res.get("error"):
        return f"не вышло: {res['error']}"
    if name == "search_places":
        return f"найдено мест: {res.get('count', 0)} — " + ", ".join(p["name"] for p in res.get("places", [])[:3])
    if name == "get_weather":
        days = res.get("days", [])
        risky = [d["date"][5:] for d in days if d.get("risks")]
        src = "Open-Meteo" if res.get("source") == "open-meteo" else res.get("source")
        return f"прогноз на {len(days)} дн. ({src})" + (f", риски: {', '.join(risky)}" if risky else ", без рисков")
    if name == "build_route":
        mode = {"car": "на машине", "bike": "на велосипеде", "foot": "пешком"}.get(res.get("mode"), res.get("mode"))
        src = {"osrm": "OSRM", "estimate": "оценка"}.get(res.get("source"), res.get("source"))
        return f"{res.get('distance_km')} км, {res.get('duration_h')} ч {mode} ({src})"
    if name == "find_fuel_stations":
        return f"АЗС по пути: {len(res.get('stations', []))}, с {res.get('fuel')}: {res.get('stations_with_fuel')}, " \
               f"макс. перегон {res.get('max_gap_km')} км"
    if name == "find_lodging":
        free = [o["name"] for o in res.get("options", []) if o.get("available")]
        return f"свободно вариантов: {len(free)}" + (f" — {free[0]}" if free else "")
    if name == "public_transport":
        return f"рейсов: {len(res.get('trips', []))}" + (f" — {res['trips'][0]['title']}" if res.get("trips") else "")
    if name == "find_events":
        return f"событий: {len(res.get('events', []))}"
    if name == "geocode":
        r = res.get("results") or []
        return f"{r[0]['lat']}, {r[0]['lon']} ({res.get('source')})" if r else "не найдено"
    if name == "find_food":
        p = res.get("places") or []
        return f"заведений рядом: {len(p)}" + (f" — {p[0]['name']}" + (f" ({p[0]['cuisine']})" if p[0].get("cuisine") else "") if p else "")
    if name == "place_info":
        return (res.get("extract") or "")[:90] + "…"
    return "готово"


def _parse_args(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        val = json.loads(raw or "{}")
        return val if isinstance(val, dict) else {}
    except json.JSONDecodeError:
        return {"__invalid_json__": str(raw)[:200]}


def _extract_plan(args: dict) -> dict:
    plan = args.get("plan", args)
    if isinstance(plan, str):  # некоторые модели кладут план строкой
        try:
            plan = json.loads(plan)
        except json.JSONDecodeError:
            plan = {}
    if not isinstance(plan, dict):
        return {}
    for key in ("days", "cautions", "weather_notes", "fuel_stops"):  # вложенные поля тоже бывают строками
        if isinstance(plan.get(key), str):
            try:
                plan[key] = json.loads(plan[key])
            except json.JSONDecodeError:
                plan[key] = [] if key == "days" else [plan[key]]
    return plan


async def _noop(_: dict) -> None:
    return None


async def enrich_map(plan: dict, ctx: ToolContext) -> dict:
    """Геометрия маршрута по дням для карты — считается на сервере, LLM-токены на это не тратятся."""
    mode = plan_transport(plan, parse_intents("", ctx.today))
    routing_mode = mode if mode in ("car", "bike", "foot") else "car"
    days_out = []

    async def one(i: int, day: dict) -> dict:
        markers = []
        for it in day.get("items") or []:
            try:
                markers.append({"name": it.get("name"), "lat": float(it["lat"]), "lon": float(it["lon"]),
                                "type": it.get("type"), "time": it.get("time")})
            except (KeyError, TypeError, ValueError):
                continue
        lod = day.get("lodging") or {}
        if lod.get("lat") and lod.get("lon"):
            markers.append({"name": lod.get("name"), "lat": float(lod["lat"]), "lon": float(lod["lon"]), "type": "lodging"})
        geometry: list = []
        approx = False
        if len(markers) >= 2:
            r = await build_route({"mode": routing_mode, "points": markers, "_full_geometry": True}, ctx)
            geometry = r.get("geometry") or []
            approx = r.get("source") != "osrm"
        return {"day": i + 1, "color": DAY_COLORS[i % len(DAY_COLORS)], "markers": markers, "geometry": geometry,
                "approx": approx, "mode": routing_mode}

    days_out = await asyncio.gather(*(one(i, d) for i, d in enumerate(plan.get("days") or [])))
    fuel = [s for f in ctx.fuel.values() for s in f.get("stations", [])][:40]
    return {"days": list(days_out), "fuel": fuel, "mode": mode}


def make_llm(version: AgentVersion) -> ChatModel:
    if not settings.openrouter_api_key:
        from .demo_llm import DemoLLM  # без ключа приложение работает на детерминированном демо-планировщике

        return DemoLLM()
    return OpenRouterLLM(version.model, api_key=settings.key_for(version.key))


async def run_agent(
    query: str,
    version: str = "v2",
    llm: ChatModel | None = None,
    today: date | None = None,
    on_event: EventCb | None = None,
    offline: bool | None = None,
    answers: list[dict] | None = None,
    allow_questions: bool = True,
    profile_hint: str = "",
) -> dict:
    emit = on_event or _noop
    t0 = time.perf_counter()
    ver = versions().get(version) or versions()["v2"]
    today = today or today_local()
    already_asked = answers is not None  # пустой список = «пропустить вопросы»
    answers = [a for a in (answers or []) if str(a.get("answer") or "").strip()]
    answers_text = "\n".join(f"- {a.get('question', '')}: {a['answer']}" for a in answers)
    intents = parse_intents(f"{query}\n{answers_text}", today)
    usage = Usage()
    trace: list[dict] = []
    tools_called: list[str] = []
    ctx = ToolContext(today=today, compact=ver.compact, offline=settings.offline if offline is None else offline)

    def finish(status: str, **extra: Any) -> dict:
        metrics = {**usage.dict(), "latency_s": round(time.perf_counter() - t0, 2), "steps": len(trace),
                   # демо-планировщик не тратит денег: его «токены» — грубая оценка, не биллинг
                   "estimated": getattr(llm, "model", "").startswith("demo/"),
                   "tools_called": tools_called}
        return {"status": status, "query": query, "version": ver.key, "version_label": ver.label,
                "model": getattr(llm, "model", ver.model), "intents": intents.dict(), "metrics": metrics,
                "trace": trace, "sources": sorted(ctx.sources), **extra}

    await emit({"type": "start", "version": ver.key, "intents": intents.dict()})

    if ver.prefilter:
        verdict = precheck(f"{query}\n{answers_text}".strip(), settings.max_query_chars)  # ответы — тоже ввод пользователя
        if not verdict.allowed:
            trace.append({"kind": "guard", "name": "precheck", "summary": f"отклонено пред-фильтром: {verdict.category}"})
            await emit({"type": "guard", "category": verdict.category})
            return finish("declined", refusal={"category": verdict.category, "message": verdict.message, "by": "prefilter"})

    if llm is None:
        try:
            llm = make_llm(ver)
        except LLMError as exc:
            return finish("error", error=str(exc))

    system = full_prompt(today) if ver.prompt == "full" else baseline_prompt(today)
    user_text = query[:2000] + (f"\n\nУточнения клиента:\n{answers_text}" if answers_text else "")
    if profile_hint:  # анкета из профиля: учитываем и не переспрашиваем
        user_text += f"\n\nИз профиля клиента (учитывай, не переспрашивай): {profile_hint[:600]}"
    messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user_text}]
    can_ask = allow_questions and not already_asked and ver.prompt == "full"  # спрашиваем максимум один раз
    tool_schemas = [t.schema() for t in ALL_TOOLS.values()] + FINISH_TOOLS + ([ASK_TOOL] if can_ask else [])
    repairs_left = ver.max_repairs
    nudged = False
    truncated = False
    last_plan: dict | None = None
    last_checks: list = []

    for step in range(1, ver.max_steps + 1):
        await emit({"type": "thinking", "step": step})
        ts = time.perf_counter()
        try:
            resp = await llm.chat(messages, tool_schemas)
        except LLMError as exc:
            return finish("error", error=str(exc))
        dt = time.perf_counter() - ts
        usage.add(resp.usage, dt)
        msg = resp.message
        calls = msg.get("tool_calls") or []
        trace.append({"kind": "llm", "step": step, "ms": int(dt * 1000),
                      "tokens": int((resp.usage or {}).get("total_tokens") or 0), "tool_calls": len(calls)})

        if not calls:
            text = (msg.get("content") or "").strip()
            if resp.finish_reason == "length" and ver.repair and not truncated:
                truncated = True  # план не влез в лимит токенов — просим компактнее
                messages.append({"role": "assistant", "content": text[:2000] or "…"})
                messages.append({"role": "user", "content": TRUNCATED_NUDGE})
                continue
            if ver.repair and not nudged:
                nudged = True
                messages.append({"role": "assistant", "content": text or "…"})
                messages.append({"role": "user", "content": REPAIR_NUDGE})
                continue
            return finish("text", text=text or "Модель не вернула ответа.")

        assistant = {"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls}
        if msg.get("reasoning_details"):
            assistant["reasoning_details"] = msg["reasoning_details"]  # нужно Gemini/o-моделям для продолжения цикла
        messages.append(assistant)

        ask = next((c for c in calls if c["function"]["name"] == "ask_user"), None)
        if ask and can_ask:
            qs = []
            for q in (_parse_args(ask["function"].get("arguments")).get("questions") or [])[:2]:
                opts = [str(o)[:40] for o in (q.get("options") or []) if str(o).strip()][:4]
                if str(q.get("text") or "").strip() and len(opts) >= 2:
                    qs.append({"text": str(q["text"])[:120], "options": opts})
            if qs:
                tools_called.append("ask_user")
                trace.append({"kind": "tool", "step": step, "name": "ask_user", "summary": f"вопросов: {len(qs)}"})
                await emit({"type": "tool", "name": "ask_user", "args": ""})
                return finish("question", questions=qs)
        calls = [c for c in calls if c["function"]["name"] != "ask_user"]
        regular = [c for c in calls if c["function"]["name"] not in ("submit_plan", "decline_request")]
        final = [c for c in calls if c["function"]["name"] in ("submit_plan", "decline_request")]

        async def run_one(call: dict) -> tuple[dict, str]:
            name = call["function"]["name"]
            args = _parse_args(call["function"].get("arguments"))
            tools_called.append(name)
            await emit({"type": "tool", "name": name, "args": _short(args, 200)})
            t1 = time.perf_counter()
            tool = ALL_TOOLS.get(name)
            if tool is None:
                full = visible = {"error": f"нет такого тула: {name}"}
            elif "__invalid_json__" in args:
                full = visible = {"error": "аргументы — невалидный JSON"}
            else:
                try:
                    full, visible = await tool.run(args, ctx)
                except Exception as exc:  # тул не должен ронять агента
                    full = visible = {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}
            summary = describe_tool(name, full)
            trace.append({"kind": "tool", "step": step, "name": name, "args": _short(args), "summary": summary,
                          "ms": int((time.perf_counter() - t1) * 1000)})
            await emit({"type": "tool_result", "name": name, "summary": summary})
            return call, _dump(visible, ver.compact)

        results = await asyncio.gather(*(run_one(c) for c in regular))
        for call, content in results:
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
        if ver.repair and not final and step == ver.max_steps - 2:
            messages.append({"role": "user", "content": LAST_STEPS_NUDGE})  # не даём агенту уйти в бесконечный сбор данных

        for idx, call in enumerate(final):
            name = call["function"]["name"]
            args = _parse_args(call["function"].get("arguments"))
            tools_called.append(name)
            if name == "decline_request":
                trace.append({"kind": "tool", "step": step, "name": name, "summary": args.get("category", "")})
                await emit({"type": "tool", "name": name, "args": args.get("category", "")})
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": "ok"})
                return finish("declined", refusal={"category": args.get("category", "off_topic"),
                                                   "message": args.get("message") or "Сие не о странствиях по Приморью.",
                                                   "by": "llm"})
            plan = _extract_plan(args)
            await emit({"type": "tool", "name": "submit_plan", "args": f"дней: {len(plan.get('days') or [])}"})
            checks = await validate_plan(plan, intents, ctx)
            summ = summarize(checks)
            last_plan, last_checks = plan, checks
            failed = [c for c in checks if not c.ok and c.severity == "error"]
            trace.append({"kind": "check", "step": step, "name": "validate_plan",
                          "summary": f"сверка {summ['passed']}/{summ['total']}" + (f", ошибок {len(failed)}" if failed else "")})
            await emit({"type": "check", "summary": summ, "failed": [c.text for c in failed]})
            if failed and ver.repair and repairs_left > 0:
                repairs_left -= 1
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": _dump({
                    "accepted": False, "errors": [c.text for c in failed],
                    "hint": "Исправь эти противоречия (тулы можно вызвать снова) и вызови submit_plan ещё раз.",
                }, ver.compact)})
                for rest in final[idx + 1:]:  # на каждый tool_call обязан быть ответ
                    messages.append({"role": "tool", "tool_call_id": rest["id"], "content": "skipped"})
                break
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": '{"accepted":true}'})
            return await _finalize(plan, checks, ctx, finish, emit)

    if last_plan is not None:  # шаги кончились, но план был — отдаём лучший с честной сверкой
        return await _finalize(last_plan, last_checks, ctx, finish, emit)
    return finish("error", error=f"агент не уложился в {ver.max_steps} шагов")


def attach_links(plan: dict) -> None:
    """Ссылки, по которым человек сам всё оформит. Считаются на сервере — модель их не выдумывает."""
    for day in plan.get("days") or []:
        date_s = str(day.get("date") or "")[:10]
        for it in day.get("items") or []:
            links = []
            try:
                lat, lon = float(it["lat"]), float(it["lon"])
            except (KeyError, TypeError, ValueError):
                lat = lon = None
            if it.get("trip_id"):
                trip = get_trip(str(it["trip_id"]))
                if trip:
                    src, dst = (trip["from"], trip["to"]) if trip["direction"] != "back" else (trip["to"], trip["from"])
                    links.append({"title": "Расписание и билеты", "url": rasp(src, dst, date_s, trip["type"])})
            elif it.get("type") in ("place", "food") and it.get("name"):
                place = get_place(str(it.get("place_id") or ""))
                if place and lat is None:
                    lat, lon = place["lat"], place["lon"]
                url = str(it.get("url") or "")
                if url.startswith(("http://", "https://")):
                    links.append({"title": "Сайт", "url": url})
                links.append({"title": "На карте", "url": yandex_maps(it["name"], lat, lon)})
            if links:
                it["links"] = links
        lod = day.get("lodging") or {}
        if lod.get("name"):
            lod["links"] = [{"title": "Гостиницы рядом", "url": yandex_maps("гостиницы", lod.get("lat"), lod.get("lon"), zoom=14)}]


async def _finalize(plan: dict, checks: list, ctx: ToolContext, finish, emit: EventCb) -> dict:
    attach_links(plan)
    mp = await enrich_map(plan, ctx)
    for day in plan.get("days") or []:
        fc = day.pop("_forecast", None)
        if fc:
            day["weather"] = {k: fc.get(k) for k in ("summary", "tmin", "tmax", "precip_mm", "wind_max_ms", "sunset", "risks")}
    result = finish("plan", plan=plan, checks=[c.dict() for c in checks], check_summary=summarize(checks), map=mp)
    await emit({"type": "done"})
    return result
