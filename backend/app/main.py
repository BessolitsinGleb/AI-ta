"""FastAPI: API агента + раздача фронтенда."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from fastapi.concurrency import run_in_threadpool

from . import accounts, dialog, ratelimit
from .accounts import optional_user, profile_hint, save_trip, update_trip
from .store import store
from .agent import run_agent, today_local, versions
from .db import SessionLocal, init_db
from .config import FRONTEND_DIR, settings
from .http import close_client

EXAMPLES = [
    "Хочу на эти выходные поездить по Приморью на машине с ночёвкой, не больше двух дней",
    "В субботу на автобусе в Находку на один день, хочу подняться на гору Сестра",
    "Велопрогулка по острову Русский завтра, часа на четыре",
    "Пешком по центру Владивостока в понедельник — история и виды",
    "С детьми на выходные: тигры и океанариум, едем на машине",
    "На 3 дня на машине в Хасанский район: море, бухта Витязь и «Земля леопарда»",
]

_slots = asyncio.Semaphore(4)  # не больше 4 агентов одновременно — бережём ключ и открытые API


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield
    await close_client()


app = FastAPI(title="Амба — AI-ассистент путешествий по Приморью", version="1.0.0", lifespan=lifespan)


MAX_BODY_BYTES = 16 * 1024  # запрос + ответы на вопросы укладываются в пару килобайт


@app.middleware("http")
async def limit_body(request: Request, call_next):
    """Слишком большое тело запроса отклоняем до разбора JSON."""
    if request.method == "POST":
        size = request.headers.get("content-length", "")
        if not size.isdigit():
            return JSONResponse({"detail": "Нужен заголовок Content-Length"}, status_code=411)
        if int(size) > MAX_BODY_BYTES:
            return JSONResponse({"detail": f"Запрос слишком большой: максимум {MAX_BODY_BYTES // 1024} КБ"}, status_code=413)
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Понятная ошибка без эха присланных данных."""
    errors = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]) or "body", "problem": e.get("type", "invalid")}
              for e in exc.errors()[:10]]
    return JSONResponse({"detail": "Некорректный запрос", "errors": errors}, status_code=422)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field("", max_length=200)
    answer: str = Field("", max_length=200)


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # лишние поля — ошибка 422, а не молчаливое игнорирование

    query: str = Field(..., min_length=1, max_length=2000)
    version: str | None = None
    answers: list[Answer] | None = Field(None, max_length=4)
    conversation_id: str | None = Field(None, pattern=r"^[a-f0-9]{32}$")  # доработка плана в диалоге

    def answer_dicts(self) -> list[dict] | None:
        return [a.model_dump() for a in self.answers] if self.answers is not None else None


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "llm": "openrouter" if settings.openrouter_api_key else "demo",
            "store": store.kind if store.ping() else f"{store.kind}-down",
            "default_version": settings.default_version, "today": today_local().isoformat()}


@app.get("/api/versions")
async def get_versions() -> dict:
    return {"default": settings.default_version, "demo": not settings.openrouter_api_key, "login_required": settings.require_login,
            "versions": [{"key": v.key, "label": v.label, "model": v.model} for v in versions().values()]}


@app.get("/api/examples")
async def examples() -> list[str]:
    return EXAMPLES


async def _account(request: Request):
    """Залогиненный пользователь (если есть) и подсказка агенту из его анкеты."""
    def load():
        with SessionLocal() as db:
            user = optional_user(request, db)
            return user, (profile_hint(user) if user and user.onboarded else "")
    return await run_in_threadpool(load)


def _version(v: str | None) -> str:
    key = v or settings.default_version
    if key not in versions():
        raise HTTPException(400, f"неизвестная версия {key}")
    return key


def _limit_plans(request: Request, user) -> None:
    """Защита от спама: каждый план стоит денег. Счётчики в Redis — общие для всех копий приложения."""
    ip = ratelimit.client_ip(request)
    ratelimit.check(f"plan:ip:{ip}:min", settings.plan_limit_min, 60)
    ratelimit.check(f"plan:ip:{ip}:hour", settings.plan_limit_hour, 3600)
    if user is not None:
        ratelimit.check(f"plan:user:{user.id}:hour", settings.plan_limit_user_hour, 3600)


async def _prepare(req: PlanRequest, request: Request):
    """Пользователь, подсказка из анкеты и (для доработки) диалог. Всё, что может отказать, — до старта агента."""
    user, hint = await _account(request)
    if user is None and settings.require_login:
        raise HTTPException(401, "Войдите, чтобы Амба собрала план", headers={"WWW-Authenticate": "Bearer"})
    _limit_plans(request, user)
    conv = None
    if req.conversation_id:
        conv = dialog.load(req.conversation_id, user.id if user else None)
        if conv is None:
            raise HTTPException(404, "Диалог устарел или не найден — соберите план заново")
        if not dialog.public(conv)["can_refine"]:
            raise HTTPException(409, "Это уже много правок — соберите новый план с учётом пожеланий")
    return user, hint, conv


async def _run(req: PlanRequest, version: str, user, hint: str, conv: dict | None, on_event=None) -> dict:
    refine = dialog.refine_context(conv) if conv else None
    result = await run_agent(req.query, version, on_event=on_event, answers=req.answer_dicts(), profile_hint=hint, refine=refine)
    if result.get("status") == "plan" and user is not None:
        base_query = conv["query"] if conv else req.query

        def store_trip():
            with SessionLocal() as db:
                u = db.merge(user)
                if conv and conv.get("trip_id"):
                    return update_trip(db, u, conv["trip_id"], base_query, result)
                return save_trip(db, u, base_query, result).id
        result["trip_id"] = await run_in_threadpool(store_trip)
    if conv:
        conv = dialog.record(conv, req.query, result)
    elif result.get("status") == "plan":
        conv = dialog.start(user.id if user else None, req.query, req.answer_dicts(), result)
    if conv:
        result["conversation"] = dialog.public(conv)
    return result


@app.post("/api/plan")
async def plan(req: PlanRequest, request: Request) -> dict:
    version = _version(req.version)
    user, hint, conv = await _prepare(req, request)
    async with _slots:
        return await _run(req, version, user, hint, conv)


@app.post("/api/plan/stream")
async def plan_stream(req: PlanRequest, request: Request) -> StreamingResponse:
    version = _version(req.version)
    user, hint, conv = await _prepare(req, request)  # 429/404 — обычным JSON, до открытия стрима
    queue: asyncio.Queue = asyncio.Queue()

    async def on_event(ev: dict) -> None:
        await queue.put(ev)

    async def worker() -> None:
        async with _slots:
            try:
                result = await _run(req, version, user, hint, conv, on_event)
                await queue.put({"type": "result", "result": result})
            except Exception as exc:  # pragma: no cover — страховка, чтобы стрим не повис
                await queue.put({"type": "result", "result": {"status": "error", "error": f"{type(exc).__name__}: {exc}"}})
            finally:
                await queue.put(None)

    async def gen():
        task = asyncio.create_task(worker())
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # держим соединение за прокси
                    continue
                if ev is None:
                    break
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


app.include_router(accounts.router)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")
