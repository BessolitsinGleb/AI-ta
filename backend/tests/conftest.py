import os
import sys
from pathlib import Path

# Тесты не ходят в сеть и не тратят ключ: офлайн-режим и пустой ключ выставляются до импорта приложения.
os.environ["OFFLINE_MODE"] = "1"
os.environ["OPENROUTER_API_KEY"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.http import clear_cache  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()
