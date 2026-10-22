"""Диалог с клиентом поверх плана: «сделай подешевле», «убери музей» — агент дорабатывает текущий план.

История хранится в Redis 24 часа (без Redis — в памяти). Идентификатор диалога — случайный, у залогиненных
он ещё и привязан к владельцу.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .store import store

TTL_S = 24 * 3600
MAX_REFINES = 8


def _key(conv_id: str) -> str:
    return f"conv:{conv_id}"


def compact_plan(plan: dict) -> dict:
    """Короткая версия плана для контекста модели: без геометрии, описаний и ссылок."""
    days = []
    for d in plan.get("days") or []:
        items = [{k: it[k] for k in ("time", "type", "name", "place_id", "trip_id") if it.get(k)} for it in d.get("items") or []]
        day = {"date": d.get("date"), "title": d.get("title"), "items": items}
        if (d.get("lodging") or {}).get("name"):
            day["lodging"] = d["lodging"]["name"]
        days.append(day)
    return {"title": plan.get("title"), "transport": plan.get("transport"), "days": days, "cautions": plan.get("cautions") or []}


def reply_text(result: dict) -> str:
    """Что Амба «ответил» в чате на этот шаг."""
    if result.get("status") == "plan":
        plan = result.get("plan") or {}
        ok = (result.get("check_summary") or {}).get("converges")
        tail = "Все проверки пройдены." if ok else "Есть замечания — смотрите блок проверок."
        return f"{plan.get('title') or 'План готов'}. {tail}"
    if result.get("status") == "declined":
        return (result.get("refusal") or {}).get("message") or "Это не про поездку по Приморью."
    if result.get("status") == "question":
        return " ".join(q["text"] for q in result.get("questions") or [])
    return result.get("error") or "Не получилось, попробуйте ещё раз."


def public(conv: dict) -> dict:
    refines = sum(1 for t in conv["turns"] if t["role"] == "user") - 1
    return {"id": conv["id"], "turns": conv["turns"], "can_refine": refines < MAX_REFINES}


def start(owner: str | None, query: str, answers: list[dict] | None, result: dict) -> dict:
    conv = {"id": uuid.uuid4().hex, "owner": owner, "query": query, "answers": answers or [], "trip_id": result.get("trip_id"),
            "plan": compact_plan(result.get("plan") or {}), "created": datetime.now(timezone.utc).isoformat(),
            "turns": [{"role": "user", "text": query[:500]}, {"role": "assistant", "text": reply_text(result)}]}
    store.set_json(_key(conv["id"]), conv, TTL_S)
    return conv


def load(conv_id: str, owner: str | None) -> dict | None:
    conv = store.get_json(_key(conv_id))
    if not conv or (conv.get("owner") and conv["owner"] != owner):
        return None  # чужой диалог неотличим от истёкшего
    return conv


def record(conv: dict, message: str, result: dict) -> dict:
    conv["turns"] += [{"role": "user", "text": message[:500]}, {"role": "assistant", "text": reply_text(result)}]
    if result.get("status") == "plan":
        conv["plan"] = compact_plan(result.get("plan") or {})
    if result.get("trip_id"):
        conv["trip_id"] = result["trip_id"]
    store.set_json(_key(conv["id"]), conv, TTL_S)  # каждый ответ продлевает жизнь диалога
    return conv


def refine_context(conv: dict) -> dict:
    earlier = [t["text"] for t in conv["turns"][2::2]]  # прошлые просьбы клиента, кроме исходного запроса
    return {"query": conv["query"], "answers": conv.get("answers") or [], "plan_json": json.dumps(conv["plan"], ensure_ascii=False),
            "earlier": earlier[-4:]}
