import os
import sys
from pathlib import Path

# Тесты не ходят в сеть и не тратят ключ: офлайн-режим и пустой ключ выставляются до импорта приложения.
os.environ["OFFLINE_MODE"] = "1"
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["SMTP_PASSWORD"] = ""  # письма не уходят, а попадают в mailer.outbox
os.environ["SMTP_USER"] = ""
os.environ["REDIS_URL"] = ""  # тесты — на памяти; Redis проверяется отдельно через fakeredis
os.environ["REQUIRE_LOGIN"] = "0"  # тесты агента идут гостем; запрет для гостей — в test_accounts
os.environ["JWT_SECRET"] = "test-secret-" + "x" * 32
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(__file__).parent / ".test.db")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.http import clear_cache  # noqa: E402


from app import mailer, ratelimit  # noqa: E402
from app.db import Base, engine  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_state():
    clear_cache()
    ratelimit.reset()
    mailer.outbox.clear()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    clear_cache()
