#!/usr/bin/env bash
# Деплой на выданную VM: ./deploy/deploy.sh user@IP [порт]
# Требуется: SSH-доступ по ключу, на VM — Docker (скрипт поставит его сам на Ubuntu/Debian).
set -euo pipefail
TARGET="${1:?usage: deploy.sh user@host [port]}"
PORT="${2:-8000}"
APP_DIR="amba-travel-agent"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "→ копирую код на $TARGET:~/$APP_DIR"
rsync -az --delete \
  --exclude .venv --exclude node_modules --exclude .git --exclude __pycache__ --exclude .pytest_cache \
  --exclude 'presentation/node_modules' --exclude .env \
  "$ROOT/" "$TARGET:~/$APP_DIR/"

if [ -f "$ROOT/.env" ]; then
  echo "→ копирую .env (ключ OpenRouter)"
  scp -q "$ROOT/.env" "$TARGET:~/$APP_DIR/.env"
fi

ssh "$TARGET" bash -s <<REMOTE
set -euo pipefail
cd ~/$APP_DIR
touch .env
if ! command -v docker >/dev/null 2>&1; then
  echo "→ ставлю Docker"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "\$USER" || true
fi
SUDO=""; docker info >/dev/null 2>&1 || SUDO="sudo"
PORT=$PORT \$SUDO docker compose up -d --build
sleep 3
curl -fsS "http://127.0.0.1:$PORT/api/health" && echo
REMOTE

HOST="${TARGET#*@}"
echo "✓ Готово: http://$HOST:$PORT"
