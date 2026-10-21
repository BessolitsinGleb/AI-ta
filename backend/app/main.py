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

from .agent import run_agent, today_local, versions
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

    def answer_dicts(self) -> list[dict] | None:
        return [a.model_dump() for a in self.answers] if self.answers is not None else None


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "llm": "openrouter" if settings.openrouter_api_key else "demo",
            "default_version": settings.default_version, "today": today_local().isoformat()}


@app.get("/api/versions")
async def get_versions() -> dict:
    return {"default": settings.default_version, "demo": not settings.openrouter_api_key,
            "versions": [{"key": v.key, "label": v.label, "model": v.model} for v in versions().values()]}


@app.get("/api/examples")
async def examples() -> list[str]:
    return EXAMPLES


def _version(v: str | None) -> str:
    key = v or settings.default_version
    if key not in versions():
        raise HTTPException(400, f"неизвестная версия {key}")
    return key


@app.post("/api/plan")
async def plan(req: PlanRequest) -> dict:
    async with _slots:
        return await run_agent(req.query, _version(req.version), answers=req.answer_dicts())


@app.post("/api/plan/stream")
async def plan_stream(req: PlanRequest) -> StreamingResponse:
    version = _version(req.version)
    queue: asyncio.Queue = asyncio.Queue()

    async def on_event(ev: dict) -> None:
        await queue.put(ev)

    async def worker() -> None:
        async with _slots:
            try:
                result = await run_agent(req.query, version, on_event=on_event, answers=req.answer_dicts())
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


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")
