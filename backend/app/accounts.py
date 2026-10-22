"""API аккаунтов: регистрация с подтверждением почты, JWT-сессии, профиль с анкетой, история поездок, рекомендации."""
from __future__ import annotations

import collections
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from urllib.parse import quote

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import mailer, ratelimit, recommend, security
from .config import settings
from .db import RefreshSession, Trip, User, get_db, utcnow
from .tools.places import get_place

router = APIRouter(prefix="/api")
COOKIE = "amba_refresh"
DB = Annotated[Session, Depends(get_db)]
GENERIC_SENT = {"ok": True, "message": "Если адрес есть в системе, письмо уже отправлено. Проверьте почту."}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _password_ok(v: str) -> str:
    if len(v) < 8:
        raise ValueError("пароль — минимум 8 символов")
    if v.isdigit() or v.isalpha():
        raise ValueError("пароль должен содержать и буквы, и цифры")
    return v


class RegisterIn(Strict):
    email: EmailStr
    password: str = Field(max_length=128)
    name: str = Field("", max_length=80)
    _pw = field_validator("password")(_password_ok)


class LoginIn(Strict):
    email: EmailStr
    password: str = Field(max_length=128)


class EmailIn(Strict):
    email: EmailStr


class ResetIn(Strict):
    token: str = Field(max_length=2000)
    password: str = Field(max_length=128)
    _pw = field_validator("password")(_password_ok)


class ChangePasswordIn(Strict):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)
    _pw = field_validator("new_password")(_password_ok)


InterestKey = Literal["sea", "history", "hiking", "animals", "nature", "food", "views"]
TransportKey = Literal["car", "public", "bike", "foot"]


class ProfileIn(Strict):
    name: str | None = Field(None, max_length=80)
    home_city: str | None = Field(None, max_length=80)
    interests: list[InterestKey] | None = Field(None, max_length=7)
    transport: list[TransportKey] | None = Field(None, max_length=4)
    companions: Literal["solo", "couple", "friends", "kids", ""] | None = None
    budget: Literal["low", "mid", "high", ""] | None = None
    pace: Literal["calm", "balanced", "active", ""] | None = None
    onboarded: bool | None = None


class FavoriteIn(Strict):
    favorite: bool


def norm_email(e: str) -> str:
    return e.strip().lower()


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "verified": u.verified, "created_at": u.created_at.isoformat(),
            "onboarded": u.onboarded, "home_city": u.home_city, "interests": u.interests or [], "transport": u.transport or [],
            "companions": u.companions, "budget": u.budget, "pace": u.pace}


# ---------- зависимости ----------

def _bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else None


def _user_from_token(token: str, db: Session) -> User | None:
    try:
        data = security.decode(token, "access")
    except jwt.PyJWTError:
        return None
    user = db.get(User, data["sub"])
    if not user or user.token_version != data.get("tv") or not user.verified:
        return None
    return user


def current_user(request: Request, db: DB) -> User:
    token = _bearer(request)
    user = _user_from_token(token, db) if token else None
    if not user:
        raise HTTPException(401, "Нужно войти", headers={"WWW-Authenticate": "Bearer"})
    return user


def optional_user(request: Request, db: Session) -> User | None:
    token = _bearer(request)
    return _user_from_token(token, db) if token else None


CurrentUser = Annotated[User, Depends(current_user)]


# ---------- сессии ----------

def _issue(response: Response, user: User, db: Session, request: Request) -> dict:
    sess = RefreshSession(user_id=user.id, expires_at=utcnow() + timedelta(days=settings.refresh_ttl_days),
                          user_agent=request.headers.get("user-agent", "")[:200])
    db.add(sess)
    db.commit()
    response.set_cookie(COOKIE, security.refresh_token(user.id, sess.jti), max_age=settings.refresh_ttl_days * 86400,
                        httponly=True, secure=settings.cookie_secure, samesite="strict", path="/api/auth")
    return {"access_token": security.access_token(user.id, user.token_version), "token_type": "bearer",
            "expires_in": settings.access_ttl_min * 60, "user": user_out(user)}


def _revoke_all(user: User, db: Session) -> None:
    now = utcnow()
    for s in db.scalars(select(RefreshSession).where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))):
        s.revoked_at = now


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite возвращает время без часового пояса


# ---------- auth ----------

@router.post("/auth/register", status_code=202)
async def register(body: RegisterIn, request: Request, db: DB) -> dict:
    ratelimit.check(f"register:{ratelimit.client_ip(request)}", 5, 3600)
    email = norm_email(body.email)
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, password_hash=security.hash_password(body.password), name=body.name.strip())
        db.add(user)
        db.commit()
    elif user.verified:
        return GENERIC_SENT  # не раскрываем, что почта уже занята
    ratelimit.check(f"mail:{email}", 3, 3600)
    url = f"{settings.public_url}/api/auth/verify?token={quote(security.verify_email_token(user.id, user.email))}"
    await mailer.send(mailer.verify_mail(user.email, user.name, url))
    return GENERIC_SENT


@router.get("/auth/verify", include_in_schema=False)
def verify(token: str, request: Request, db: DB):
    try:
        data = security.decode(token, "verify")
    except jwt.PyJWTError:
        return RedirectResponse("/#/login?verify=expired", status_code=303)
    user = db.get(User, data["sub"])
    if not user or user.email != data.get("email"):
        return RedirectResponse("/#/login?verify=expired", status_code=303)
    if not user.verified:
        user.email_verified_at = utcnow()
        db.commit()
    resp = RedirectResponse("/#/welcome", status_code=303)
    _issue(resp, user, db, request)  # сразу входим: после подтверждения — анкета
    return resp


@router.post("/auth/resend", status_code=202)
async def resend(body: EmailIn, request: Request, db: DB) -> dict:
    ratelimit.check(f"resend:{ratelimit.client_ip(request)}", 10, 3600)
    email = norm_email(body.email)
    user = db.scalar(select(User).where(User.email == email))
    if user and not user.verified:
        ratelimit.check(f"mail:{email}", 3, 3600)
        url = f"{settings.public_url}/api/auth/verify?token={quote(security.verify_email_token(user.id, user.email))}"
        await mailer.send(mailer.verify_mail(user.email, user.name, url))
    return GENERIC_SENT


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: DB) -> dict:
    email = norm_email(body.email)
    ratelimit.check(f"login:{ratelimit.client_ip(request)}", 10, 60)
    ratelimit.check(f"login:{email}", 20, 3600)
    user = db.scalar(select(User).where(User.email == email))
    ok = security.verify_password(body.password, user.password_hash if user else security.DUMMY_HASH)
    if not user or not ok:
        raise HTTPException(401, "Неверная почта или пароль")
    if not user.verified:
        raise HTTPException(403, "Сначала подтвердите почту — ссылка в письме", headers={"X-Error-Code": "email_not_verified"})
    return _issue(response, user, db, request)


@router.post("/auth/refresh")
def refresh(request: Request, response: Response, db: DB) -> dict:
    ratelimit.check(f"refresh:{ratelimit.client_ip(request)}", 60, 60)
    raw = request.cookies.get(COOKIE)
    try:
        data = security.decode(raw or "", "refresh")
    except jwt.PyJWTError:
        raise HTTPException(401, "Сессия истекла, войдите снова")
    sess = db.get(RefreshSession, data.get("jti"))
    user = db.get(User, data["sub"])
    if not sess or not user or sess.user_id != user.id:
        raise HTTPException(401, "Сессия истекла, войдите снова")
    if sess.revoked_at is not None:
        _revoke_all(user, db)  # старый токен использован повторно — возможна кража: гасим все сессии
        db.commit()
        response.delete_cookie(COOKIE, path="/api/auth")
        raise HTTPException(401, "Сессия завершена, войдите снова")
    if _aware(sess.expires_at) < utcnow():
        raise HTTPException(401, "Сессия истекла, войдите снова")
    sess.revoked_at = utcnow()  # ротация: каждый refresh-токен одноразовый
    return _issue(response, user, db, request)


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: DB) -> dict:
    try:
        data = security.decode(request.cookies.get(COOKIE, ""), "refresh")
        sess = db.get(RefreshSession, data.get("jti"))
        if sess and sess.revoked_at is None:
            sess.revoked_at = utcnow()
            db.commit()
    except jwt.PyJWTError:
        pass
    response.delete_cookie(COOKIE, path="/api/auth")
    return {"ok": True}


@router.post("/auth/forgot", status_code=202)
async def forgot(body: EmailIn, request: Request, db: DB) -> dict:
    ratelimit.check(f"forgot:{ratelimit.client_ip(request)}", 10, 3600)
    email = norm_email(body.email)
    user = db.scalar(select(User).where(User.email == email))
    if user and user.verified:
        ratelimit.check(f"mail:{email}", 3, 3600)
        url = f"{settings.public_url}/#/reset?token={quote(security.reset_token(user.id, user.token_version))}"
        await mailer.send(mailer.reset_mail(user.email, url))
    return GENERIC_SENT


@router.post("/auth/reset")
def reset(body: ResetIn, request: Request, db: DB) -> dict:
    ratelimit.check(f"reset:{ratelimit.client_ip(request)}", 10, 3600)
    try:
        data = security.decode(body.token, "reset")
    except jwt.PyJWTError:
        raise HTTPException(400, "Ссылка устарела. Запросите сброс пароля ещё раз.")
    user = db.get(User, data["sub"])
    if not user or user.token_version != data.get("tv"):
        raise HTTPException(400, "Ссылка уже использована. Запросите сброс пароля ещё раз.")
    user.password_hash = security.hash_password(body.password)
    user.token_version += 1
    _revoke_all(user, db)
    db.commit()
    return {"ok": True, "message": "Пароль изменён. Войдите с новым паролем."}


# ---------- профиль ----------

@router.get("/me")
def me(user: CurrentUser) -> dict:
    return user_out(user)


@router.patch("/me")
def update_me(body: ProfileIn, user: CurrentUser, db: DB) -> dict:
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(user, k, v.strip() if isinstance(v, str) else v)
    db.commit()
    return user_out(user)


@router.post("/me/password")
def change_password(body: ChangePasswordIn, request: Request, response: Response, user: CurrentUser, db: DB) -> dict:
    ratelimit.check(f"chpw:{user.id}", 5, 3600)
    if not security.verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Текущий пароль указан неверно")
    user.password_hash = security.hash_password(body.new_password)
    user.token_version += 1
    _revoke_all(user, db)
    db.commit()
    return _issue(response, user, db, request)  # остальные устройства выходят, это остаётся


@router.delete("/me", status_code=204)
def delete_me(response: Response, user: CurrentUser, db: DB) -> Response:
    db.delete(user)
    db.commit()
    response.delete_cookie(COOKIE, path="/api/auth")
    response.status_code = 204
    return response


@router.get("/profile/options")
def profile_options() -> dict:
    return recommend.options()


# ---------- поездки ----------

def trip_area(result: dict) -> str:
    areas = collections.Counter()
    for d in (result.get("plan") or {}).get("days") or []:
        for it in d.get("items") or []:
            p = get_place(str(it.get("place_id") or ""))
            if p:
                areas[p["area"]] += 1
    return areas.most_common(1)[0][0] if areas else "Приморье"


def save_trip(db: Session, user: User, query: str, result: dict) -> Trip:
    plan = result.get("plan") or {}
    days = plan.get("days") or []
    trip = Trip(user_id=user.id, query=query[:2000], title=str(plan.get("title") or query)[:200], area=trip_area(result),
                start_date=str((days[0] if days else {}).get("date") or "")[:10], days=len(days),
                transport=str(plan.get("transport") or "")[:20], converges=bool((result.get("check_summary") or {}).get("converges")),
                result=result)
    db.add(trip)
    db.commit()
    return trip


def trip_out(t: Trip) -> dict:
    return {"id": t.id, "title": t.title, "query": t.query, "area": t.area, "start_date": t.start_date, "days": t.days,
            "transport": t.transport, "converges": t.converges, "favorite": t.favorite, "created_at": t.created_at.isoformat()}


def _own_trip(trip_id: str, user: User, db: Session) -> Trip:
    t = db.get(Trip, trip_id)
    if not t or t.user_id != user.id:
        raise HTTPException(404, "Поездка не найдена")  # чужие поездки неотличимы от несуществующих
    return t


@router.get("/trips")
def list_trips(user: CurrentUser, db: DB, limit: int = 50) -> list[dict]:
    q = select(Trip).where(Trip.user_id == user.id).order_by(Trip.created_at.desc()).limit(min(max(limit, 1), 200))
    return [trip_out(t) for t in db.scalars(q)]


@router.get("/trips/{trip_id}")
def get_trip(trip_id: str, user: CurrentUser, db: DB) -> dict:
    t = _own_trip(trip_id, user, db)
    return {**trip_out(t), "result": t.result}


@router.patch("/trips/{trip_id}")
def favorite_trip(trip_id: str, body: FavoriteIn, user: CurrentUser, db: DB) -> dict:
    t = _own_trip(trip_id, user, db)
    t.favorite = body.favorite
    db.commit()
    return trip_out(t)


@router.delete("/trips/{trip_id}", status_code=204)
def delete_trip(trip_id: str, user: CurrentUser, db: DB) -> Response:
    db.delete(_own_trip(trip_id, user, db))
    db.commit()
    return Response(status_code=204)


# ---------- рекомендации ----------

@router.get("/recommendations")
def recommendations(user: CurrentUser, db: DB) -> dict:
    recent = [t.area for t in db.scalars(select(Trip).where(Trip.user_id == user.id).order_by(Trip.created_at.desc()).limit(5))]
    prof = user_out(user)
    return {"trips": recommend.recommend_trips(prof, recent), "places": recommend.recommend_places(prof),
            "onboarded": user.onboarded}


def profile_hint(user: User) -> str:
    """Предпочтения из анкеты — подсказка агенту, чтобы не переспрашивать то, что человек уже рассказал."""
    o = recommend.options()
    parts = []
    if user.interests:
        parts.append("интересы: " + ", ".join(o["interests"].get(k, k).lower() for k in user.interests))
    if user.transport:
        parts.append("удобный транспорт: " + ", ".join(o["transport"].get(k, k).lower() for k in user.transport))
    for key, label in (("companions", "едет"), ("budget", "бюджет"), ("pace", "темп")):
        val = getattr(user, key)
        if val:
            parts.append(f"{label}: {o[key].get(val, val).lower()}")
    if user.home_city:
        parts.append(f"живёт в городе {user.home_city}")
    return "; ".join(parts)
