#!/usr/bin/env bash
# Амба в локальной сети: ноутбук — сервер, телефоны в том же Wi-Fi открывают http://<IP ноутбука>:8000.
# Запасной вариант на случай, если облачный деплой недоступен. IP меняется вместе с сетью — просто запустите заново.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
# Wi-Fi (en0/en1), иначе интерфейс маршрута по умолчанию — например, телефон по USB. VPN-туннели (utun) не берём.
default_ip() {
  local ifc
  ifc=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
  case "$ifc" in ""|utun*|ipsec*|ppp*) return 1 ;; esac
  ipconfig getifaddr "$ifc"
}
IP="${LAN_IP:-$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || default_ip || true)}"
if [ -z "$IP" ]; then
  echo "Не нашёл IP ноутбука: подключитесь к Wi-Fi (или раздайте с телефона) либо задайте LAN_IP=..." >&2
  exit 1
fi
URL="http://$IP:$PORT"

# PUBLIC_URL нужен, чтобы ссылки из писем (подтверждение почты, сброс пароля) открывались с телефона
PUBLIC_URL="$URL" PORT="$PORT" docker compose up -d --build

printf "Жду запуска"
for _ in $(seq 1 60); do
  curl -sf "http://localhost:$PORT/api/health" >/dev/null && break
  printf "."; sleep 1
done
echo
curl -sf "http://localhost:$PORT/api/health" >/dev/null || { echo "Приложение не ответило, смотрите: docker compose logs amba" >&2; exit 1; }

mkdir -p data
if command -v node >/dev/null && [ -d presentation/node_modules/qrcode ]; then
  node -e '
    const qr = require("./presentation/node_modules/qrcode");
    const url = process.argv[1];
    qr.toFile("data/lan-qr.png", url, { width: 900, margin: 2, color: { dark: "#0f2d3a", light: "#ffffff" } });
  ' "$URL"
  # в терминале QR из полублоков ломается от шрифта — показываем картинку
  echo "QR для экрана: data/lan-qr.png"
  [ "${NO_OPEN:-0}" = 1 ] || open data/lan-qr.png 2>/dev/null || true
fi
# QR «Приложение» в презентации — на этот же адрес (PDF пересобирается через LibreOffice, ~полминуты)
if [ "${SKIP_DECK:-0}" != 1 ] && [ -x .venv/bin/python ]; then
  .venv/bin/python presentation/set_app_qr.py "$URL" >/dev/null && echo "Презентация: QR приложения ведёт на $URL (presentation/Amba_TBank.pptx и .pdf)" \
    || echo "Презентацию обновить не вышло — запустите: .venv/bin/python presentation/set_app_qr.py $URL" >&2
fi
echo "Амба доступна в сети: $URL"
echo "Чтобы ноутбук не уснул во время показа: caffeinate -dis"
