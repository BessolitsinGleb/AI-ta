"""Redis: лимиты запросов и история диалога; доработка плана в диалоге с клиентом."""
from datetime import date

import fakeredis
import pytest
import redis
from fastapi.testclient import TestClient

from app import dialog, ratelimit, store as store_mod
from app.agent import run_agent
from app.main import app
from app.store import MemoryStore, RedisStore
from tests.helpers import ScriptedLLM, call
from tests.test_accounts import auth, login, register, verify
from tests.test_agent import GOOD_PLAN

WED = date(2026, 10, 21)
TRIP = "В субботу на автобусе в Находку на один день"


@pytest.fixture
def redis_store(monkeypatch):
    s = RedisStore(fakeredis.FakeRedis(decode_responses=True))
    for mod in (store_mod, ratelimit, dialog):
        monkeypatch.setattr(mod, "store", s)
    return s


# ---------- хранилище ----------

def test_redis_counter_window_and_json(redis_store):
    assert [redis_store.hit("k", 60)[0] for _ in range(3)] == [1, 2, 3]
    assert 0 < redis_store.hit("k", 60)[1] <= 60
    assert redis_store.r.ttl("amba:k") > 0  # окно истекает само
    redis_store.set_json("j", {"a": "привет"}, 30)
    assert redis_store.get_json("j") == {"a": "привет"} and redis_store.ping()


def test_redis_outage_falls_back_to_memory(monkeypatch):
    class Down:
        def __getattr__(self, name):
            def fail(*a, **k):
                raise redis.ConnectionError("down")
            return fail

    s = RedisStore(Down())
    assert s.hit("x", 60)[0] == 1 and s.hit("x", 60)[0] == 2  # работает на памяти
    s.set_json("y", [1], 10)
    assert s.get_json("y") == [1] and s.ping() is False


def test_ratelimit_uses_store_and_sets_retry_after(redis_store):
    for _ in range(3):
        ratelimit.check("t", 3, 60)
    with pytest.raises(Exception) as e:
        ratelimit.check("t", 3, 60)
    assert e.value.status_code == 429 and int(e.value.headers["Retry-After"]) >= 1


def test_memory_store_expires():
    m = MemoryStore()
    m.set_json("a", 1, ttl_s=-1)
    assert m.get_json("a") is None


# ---------- лимит планов ----------

def test_plan_spam_is_limited(redis_store):
    c = TestClient(app)
    codes = [c.post("/api/plan", json={"query": "Реши мне задачу по алгебре"}).status_code for _ in range(7)]
    assert codes[:6] == [200] * 6 and codes[6] == 429


# ---------- диалог ----------

def test_refine_plan_in_dialog(redis_store):
    c = TestClient(app)
    first = c.post("/api/plan", json={"query": TRIP, "answers": []}).json()
    conv = first["conversation"]
    assert first["status"] == "plan" and len(conv["turns"]) == 2 and conv["can_refine"]
    assert redis_store.r.ttl(f"amba:conv:{conv['id']}") > 3600  # история живёт в Redis сутки

    second = c.post("/api/plan", json={"query": "давай лучше на электричке", "conversation_id": conv["id"]}).json()
    assert second["status"] == "plan" and second["conversation"]["id"] == conv["id"]
    assert [t["role"] for t in second["conversation"]["turns"]] == ["user", "assistant", "user", "assistant"]
    assert second["intents"]["transport"] == "train" and second["intents"]["max_days"] == 1  # срок из исходного запроса сохранился

    off = c.post("/api/plan", json={"query": "а давай в Сочи", "conversation_id": conv["id"]}).json()
    assert off["status"] == "declined" and len(off["conversation"]["turns"]) == 6
    assert redis_store.get_json(f"conv:{conv['id']}")["plan"]["transport"] in ("train", "bus")  # план не потерян


def test_unknown_or_foreign_dialog(redis_store):
    c = TestClient(app)
    assert c.post("/api/plan", json={"query": "дешевле", "conversation_id": "0" * 32}).status_code == 404
    assert c.post("/api/plan", json={"query": "дешевле", "conversation_id": "not-hex"}).status_code == 422

    owner = TestClient(app)
    register(owner, email="o@example.com")
    verify(owner)
    tok = login(owner, email="o@example.com").json()["access_token"]
    conv = owner.post("/api/plan", headers=auth(tok), json={"query": TRIP, "answers": []}).json()["conversation"]
    assert c.post("/api/plan", json={"query": "дешевле", "conversation_id": conv["id"]}).status_code == 404  # гость не продолжит чужой


def test_refine_limit(redis_store, monkeypatch):
    monkeypatch.setattr(dialog, "MAX_REFINES", 1)
    c = TestClient(app)
    conv = c.post("/api/plan", json={"query": TRIP, "answers": []}).json()["conversation"]
    r = c.post("/api/plan", json={"query": "пораньше", "conversation_id": conv["id"]}).json()
    assert r["conversation"]["can_refine"] is False
    assert c.post("/api/plan", json={"query": "ещё", "conversation_id": conv["id"]}).status_code == 409


def test_refine_updates_saved_trip(redis_store):
    c = TestClient(app)
    register(c)
    verify(c)
    tok = login(c).json()["access_token"]
    first = c.post("/api/plan", headers=auth(tok), json={"query": TRIP, "answers": []}).json()
    second = c.post("/api/plan", headers=auth(tok), json={"query": "на электричке", "conversation_id": first["conversation"]["id"]}).json()
    assert second["trip_id"] == first["trip_id"]  # та же поездка, обновлённая
    trips = c.get("/api/trips", headers=auth(tok)).json()
    assert len(trips) == 1 and trips[0]["transport"] == "train"


@pytest.mark.asyncio
async def test_agent_gets_plan_and_request_in_context():
    llm = ScriptedLLM([[call("submit_plan", {"plan": GOOD_PLAN})]])
    refine = {"query": "В субботу по Владивостоку на машине", "answers": [{"question": "Кухня?", "answer": "Корейская"}],
              "plan_json": '{"title": "Старый план"}', "earlier": ["пораньше"]}
    r = await run_agent("убери музеи", "v2", llm=llm, today=WED, offline=True, refine=refine)
    text = llm.seen[0][1]["content"]
    assert r["status"] == "plan"
    assert "Старый план" in text and "«убери музеи»" in text and "Корейская" in text and "пораньше" in text
