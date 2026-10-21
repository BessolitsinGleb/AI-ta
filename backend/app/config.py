"""Настройки приложения: читаются из переменных окружения / файла .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

TZ = ZoneInfo("Asia/Vladivostok")
DATA_DIR = Path(__file__).resolve().parent / "data"
FRONTEND_DIR = ROOT_DIR / "frontend"


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", ""))
    openrouter_base_url: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    )
    default_version: str = field(default_factory=lambda: os.getenv("AGENT_VERSION", "v2"))
    # Модели для версий пайплайна можно переопределить без правки кода.
    model_v1: str = field(default_factory=lambda: os.getenv("MODEL_V1", "openai/gpt-4.1-mini"))
    model_v2: str = field(default_factory=lambda: os.getenv("MODEL_V2", "openai/gpt-4.1-mini"))
    model_v3: str = field(default_factory=lambda: os.getenv("MODEL_V3", "google/gemini-3.1-flash-lite"))
    llm_max_tokens: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "4096")))
    llm_timeout_s: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_S", "90")))
    http_timeout_s: float = field(default_factory=lambda: float(os.getenv("HTTP_TIMEOUT_S", "12")))
    user_agent: str = field(
        default_factory=lambda: os.getenv(
            "HTTP_USER_AGENT", "amba-travel-agent/1.0 (study project, Primorsky Krai travel planner)"
        )
    )
    max_query_chars: int = 600
    # Офлайн-режим: внешние API не вызываются, только датасеты (для тестов и демо без сети).
    offline: bool = field(default_factory=lambda: os.getenv("OFFLINE_MODE", "0") == "1")


settings = Settings()
