"""База данных: пользователи, сессии (refresh-токены) и сохранённые поездки."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(80), default="")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Растёт при смене пароля: старые ссылки сброса пароля и сессии перестают работать.
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Анкета интересов.
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False)
    home_city: Mapped[str] = mapped_column(String(80), default="Владивосток")
    interests: Mapped[list] = mapped_column(JSON, default=list)
    transport: Mapped[list] = mapped_column(JSON, default=list)
    companions: Mapped[str] = mapped_column(String(20), default="")
    budget: Mapped[str] = mapped_column(String(20), default="")
    pace: Mapped[str] = mapped_column(String(20), default="")

    trips: Mapped[list["Trip"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list["RefreshSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def verified(self) -> bool:
        return self.email_verified_at is not None


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"

    jti: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Заменён новым токеном (ротация), а не отозван выходом: такой ещё недолго принимается от соседней вкладки
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str] = mapped_column(String(200), default="")

    user: Mapped[User] = relationship(back_populates="sessions")


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    query: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(200), default="")
    area: Mapped[str] = mapped_column(String(80), default="")
    start_date: Mapped[str] = mapped_column(String(10), default="")
    days: Mapped[int] = mapped_column(Integer, default=0)
    transport: Mapped[str] = mapped_column(String(20), default="")
    converges: Mapped[bool] = mapped_column(Boolean, default=False)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[dict] = mapped_column(JSON)  # полный ответ агента: план, карта, проверки — открывается без повторного запуска

    user: Mapped[User] = relationship(back_populates="trips")


def normalize_url(url: str) -> str:
    """Хостинги (Render, Heroku) выдают postgres://… — SQLAlchemy с драйвером psycopg 3 ждёт postgresql+psycopg://."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


def _make_engine(url: str):
    url = normalize_url(url)
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
                        pool_pre_ping=not url.startswith("sqlite"))  # бесплатный Postgres рвёт простаивающие соединения
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _fk(dbapi_conn, _):  # SQLite по умолчанию не соблюдает внешние ключи
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return eng


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """create_all не меняет существующие таблицы: новые столбцы добавляем сами, данные остаются."""
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in have and col.nullable:
                with engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}'))


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
