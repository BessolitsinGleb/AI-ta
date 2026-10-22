FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY eval ./eval

RUN useradd --create-home amba && mkdir -p /app/data && chown -R amba /app
USER amba

EXPOSE 8000
ENV PORT=8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health')" || exit 1

# PORT задаёт хостинг (Railway, Render и т. п.); локально и на VM — 8000.
CMD uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips="*"
