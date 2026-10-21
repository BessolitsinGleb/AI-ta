"""FastAPI: API агента + раздача фронтенда."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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


class PlanRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    version: str | None = None


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
        return await run_agent(req.query, _version(req.version))


@app.post("/api/plan/stream")
async def plan_stream(req: PlanRequest) -> StreamingResponse:
    version = _version(req.version)
    queue: asyncio.Queue = asyncio.Queue()

    async def on_event(ev: dict) -> None:
        await queue.put(ev)

    async def worker() -> None:
        async with _slots:
            try:
                result = await run_agent(req.query, version, on_event=on_event)
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
