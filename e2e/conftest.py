import os
import socket
import sys
import threading
import time
from pathlib import Path

import tempfile

os.environ.setdefault("OPENROUTER_API_KEY", "")  # e2e идут на демо-планировщике
os.environ.setdefault("OFFLINE_MODE", "1")
os.environ["SMTP_PASSWORD"] = ""  # письма — в mailer.outbox
os.environ["JWT_SECRET"] = "e2e-secret-" + "y" * 32
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "e2e.db")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pytest  # noqa: E402
import uvicorn  # noqa: E402


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def base_url():
    from app.main import app

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
