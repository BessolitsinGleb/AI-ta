import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_and_versions():
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["llm"] == "demo"
    v = client.get("/api/versions").json()
    assert {x["key"] for x in v["versions"]} == {"v1", "v2", "v3"} and v["demo"] is True
    assert len(client.get("/api/examples").json()) >= 3


def test_index_and_static():
    r = client.get("/")
    assert r.status_code == 200 and "Амба" in r.text
    assert client.get("/static/js/render.js").status_code == 200
    assert client.get("/static/assets/amba.svg").status_code == 200


def test_plan_endpoint_returns_plan():
    r = client.post("/api/plan", json={"query": "В субботу на автобусе в Находку на один день", "version": "v2"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "plan" and body["plan"]["days"] and body["map"]["days"]


def test_plan_endpoint_declines_off_topic():
    body = client.post("/api/plan", json={"query": "Реши мне задачу по алгебре"}).json()
    assert body["status"] == "declined"


def test_bad_version_and_validation():
    assert client.post("/api/plan", json={"query": "x", "version": "v9"}).status_code == 400
    assert client.post("/api/plan", json={"query": ""}).status_code == 422


def test_stream_emits_events_and_result():
    with client.stream("POST", "/api/plan/stream", json={"query": "Пешком по Владивостоку завтра"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    types = [e["type"] for e in events]
    assert types[0] == "start" and types[-1] == "result"
    assert "tool" in types and "check" in types
    assert events[-1]["result"]["status"] == "plan"
