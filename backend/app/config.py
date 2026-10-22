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
    default_version: str = field(default_factory=lambda: os.getenv("AGENT_VERSION", "v3"))
    # Модели для версий пайплайна можно переопределить без правки кода.
    model_v1: str = field(default_factory=lambda: os.getenv("MODEL_V1", "minimax/minimax-m3.1-flash:free"))
    model_v2: str = field(default_factory=lambda: os.getenv("MODEL_V2", "minimax/minimax-m3.1-flash:free"))
    model_v3: str = field(default_factory=lambda: os.getenv("MODEL_V3", "deepseek/deepseek-v4.1-flash"))
    llm_max_tokens: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "8192")))
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

    # --- Лимиты планов (антиспам; счётчики в Redis) ---
    plan_limit_min: int = field(default_factory=lambda: int(os.getenv("PLAN_LIMIT_PER_MIN", "6")))
    plan_limit_hour: int = field(default_factory=lambda: int(os.getenv("PLAN_LIMIT_PER_HOUR", "40")))
    plan_limit_user_hour: int = field(default_factory=lambda: int(os.getenv("PLAN_LIMIT_USER_PER_HOUR", "60")))

    # --- Аккаунты ---
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", f"sqlite:///{ROOT_DIR / 'data' / 'amba.db'}"))
    jwt_secret: str = field(default_factory=lambda: os.getenv("JWT_SECRET", ""))
    access_ttl_min: int = field(default_factory=lambda: int(os.getenv("ACCESS_TTL_MIN", "15")))
    refresh_ttl_days: int = field(default_factory=lambda: int(os.getenv("REFRESH_TTL_DAYS", "30")))
    public_url: str = field(default_factory=lambda: os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/"))
    cookie_secure: bool = field(default_factory=lambda: os.getenv("COOKIE_SECURE", "0") == "1")
    # Почта: Gmail SMTP с паролем приложения. Пустой SMTP_PASSWORD — письма пишутся в лог (режим разработки).
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", "smtp.gmail.com"))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: os.getenv("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    mail_from: str = field(default_factory=lambda: os.getenv("MAIL_FROM", ""))


    def key_for(self, version: str) -> str:
        """Отдельный ключ на версию (OPENROUTER_API_KEY_V1…), иначе общий."""
        return os.getenv(f"OPENROUTER_API_KEY_{version.upper()}", "") or self.openrouter_api_key


settings = Settings()
