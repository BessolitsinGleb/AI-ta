"""Аккаунты: регистрация → письмо → подтверждение → вход → JWT-сессии, профиль, анкета, поездки, рекомендации."""
import re
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from fastapi.testclient import TestClient

from app import mailer
from app.main import app

PW = "Tiger2026!"


@pytest.fixture
def client():
    return TestClient(app)


def last_link() -> str:
    return re.search(r"https?://\S+", mailer.outbox[-1].text).group(0)


def register(client, email="amba@example.com", name="Саша"):
    r = client.post("/api/auth/register", json={"email": email, "password": PW, "name": name})
    assert r.status_code == 202
    return r


def verify(client) -> TestClient:
    path = urlparse(last_link())
    r = client.get(f"{path.path}?{path.query}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/#/welcome"
    return r


def login(client, email="amba@example.com", password=PW):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def signed_in(client) -> str:
    register(client)
    verify(client)
    return login(client).json()["access_token"]


def test_full_signup_flow(client):
    register(client)
    assert mailer.outbox[-1].to == "amba@example.com" and "/api/auth/verify?token=" in mailer.outbox[-1].text
    assert login(client).status_code == 403  # без подтверждения не пускаем
    r = verify(client)
    assert "amba_refresh" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
    r = login(client)
    assert r.status_code == 200
    me = client.get("/api/me", headers=auth(r.json()["access_token"])).json()
    assert me["email"] == "amba@example.com" and me["verified"] and not me["onboarded"]


def test_register_does_not_reveal_existing_email(client):
    signed_in(client)
    mailer.outbox.clear()
    r = register(client, name="Чужой")
    assert r.json() == {"ok": True, "message": "Если адрес есть в системе, письмо уже отправлено. Проверьте почту."}
    assert mailer.outbox == []  # подтверждённому аккаунту письмо не шлём


def test_bad_inputs(client):
    assert client.post("/api/auth/register", json={"email": "not-an-email", "password": PW}).status_code == 422
    assert client.post("/api/auth/register", json={"email": "a@example.com", "password": "12345678"}).status_code == 422
    assert client.post("/api/auth/register", json={"email": "a@example.com", "password": PW, "role": "admin"}).status_code == 422


def test_wrong_password_and_unknown_email_look_the_same(client):
    signed_in(client)
    a = login(client, password="Wrong1234")
    b = login(client, email="nobody@example.com")
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_expired_or_forged_verify_link(client):
    r = client.get("/api/auth/verify?token=garbage", follow_redirects=False)
    assert r.status_code == 303 and "expired" in r.headers["location"]


def test_refresh_rotation_and_reuse_detection(client):
    signed_in(client)
    old = client.cookies.get("amba_refresh")
    r = client.post("/api/auth/refresh")
    assert r.status_code == 200 and r.json()["access_token"]
    assert client.cookies.get("amba_refresh") != old
    client.cookies.set("amba_refresh", old, path="/api/auth")  # подсовываем уже использованный токен
    assert client.post("/api/auth/refresh").status_code == 401
    assert client.post("/api/auth/refresh").status_code == 401  # и все сессии погашены


def test_logout_revokes_session(client):
    signed_in(client)
    cookie = client.cookies.get("amba_refresh")
    assert client.post("/api/auth/logout").status_code == 200
    client.cookies.set("amba_refresh", cookie, path="/api/auth")
    assert client.post("/api/auth/refresh").status_code == 401


def test_access_token_required_and_tamper_proof(client):
    token = signed_in(client)
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers=auth(token[:-2] + "xx")).status_code == 401


def test_password_reset_is_single_use(client):
    signed_in(client)
    client.post("/api/auth/forgot", json={"email": "AMBA@example.com"})
    token = unquote(parse_qs(urlparse(last_link().replace("#/reset?", "?")).query)["token"][0])
    assert client.post("/api/auth/reset", json={"token": token, "password": "NewTiger99"}).status_code == 200
    assert client.post("/api/auth/reset", json={"token": token, "password": "Again12345"}).status_code == 400
    assert login(client).status_code == 401 and login(client, password="NewTiger99").status_code == 200


def test_change_password_logs_out_old_tokens(client):
    token = signed_in(client)
    r = client.post("/api/me/password", headers=auth(token), json={"current_password": PW, "new_password": "Changed123"})
    assert r.status_code == 200
    assert client.get("/api/me", headers=auth(token)).status_code == 401  # старый access-токен больше не действует
    assert client.get("/api/me", headers=auth(r.json()["access_token"])).status_code == 200


def test_onboarding_and_recommendations(client):
    token = signed_in(client)
    opts = client.get("/api/profile/options").json()
    assert "sea" in opts["interests"] and "kids" in opts["companions"]
    r = client.patch("/api/me", headers=auth(token), json={"interests": ["animals", "sea"], "transport": ["car"],
                                                           "companions": "kids", "pace": "calm", "onboarded": True})
    assert r.status_code == 200 and r.json()["onboarded"]
    assert client.patch("/api/me", headers=auth(token), json={"interests": ["hacking"]}).status_code == 422
    rec = client.get("/api/recommendations", headers=auth(token)).json()
    top = rec["trips"][0]
    assert top["id"] in {"safari", "khasan", "russky", "petrova"} and "подходит детям" in top["why"]
    assert rec["places"] and rec["places"][0]["map_url"].startswith("https://yandex.ru/maps/")


def test_plans_are_saved_to_history_and_private(client):
    token = signed_in(client)
    client.patch("/api/me", headers=auth(token), json={"interests": ["sea"], "onboarded": True})
    body = client.post("/api/plan", headers=auth(token), json={"query": "В субботу на автобусе в Находку на один день", "answers": []}).json()
    assert body["status"] == "plan" and body["trip_id"]
    trips = client.get("/api/trips", headers=auth(token)).json()
    assert len(trips) == 1 and trips[0]["area"] == "Находка" and trips[0]["days"] == 1
    full = client.get(f"/api/trips/{body['trip_id']}", headers=auth(token)).json()
    assert full["result"]["plan"]["days"]
    assert client.patch(f"/api/trips/{body['trip_id']}", headers=auth(token), json={"favorite": True}).json()["favorite"]

    other = TestClient(app)  # другой пользователь не видит чужую поездку
    register(other, email="other@example.com")
    verify(other)
    t2 = login(other, email="other@example.com").json()["access_token"]
    assert other.get(f"/api/trips/{body['trip_id']}", headers=auth(t2)).status_code == 404
    assert other.delete(f"/api/trips/{body['trip_id']}", headers=auth(t2)).status_code == 404

    assert client.delete(f"/api/trips/{body['trip_id']}", headers=auth(token)).status_code == 204
    assert client.get("/api/trips", headers=auth(token)).json() == []


def test_guest_plans_are_not_saved(client):
    body = client.post("/api/plan", json={"query": "В субботу на автобусе в Находку на один день", "answers": []}).json()
    assert body["status"] == "plan" and "trip_id" not in body


def test_delete_account(client):
    token = signed_in(client)
    assert client.delete("/api/me", headers=auth(token)).status_code == 204
    assert login(client).status_code == 401


def test_login_rate_limit(client):
    signed_in(client)
    codes = [login(client, password="Wrong1234").status_code for _ in range(12)]
    assert codes[-1] == 429


def test_profile_hint_reaches_agent(client, monkeypatch):
    seen = {}

    async def fake_run_agent(query, version, **kw):
        seen.update(kw)
        return {"status": "declined", "refusal": {}, "metrics": {}}

    monkeypatch.setattr("app.main.run_agent", fake_run_agent)
    token = signed_in(client)
    client.patch("/api/me", headers=auth(token), json={"interests": ["food"], "companions": "kids", "onboarded": True})
    client.post("/api/plan", headers=auth(token), json={"query": "Куда в субботу?"})
    assert "еда" in seen["profile_hint"] and "с детьми" in seen["profile_hint"]
