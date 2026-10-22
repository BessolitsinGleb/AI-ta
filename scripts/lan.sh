#!/usr/bin/env bash
# Амба в локальной сети: ноутбук — сервер, телефоны в том же Wi-Fi открывают http://<IP ноутбука>:8000.
# Запасной вариант на случай, если облачный деплой недоступен. IP меняется вместе с сетью — просто запустите заново.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
IP="${LAN_IP:-$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)}"
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
    qr.toString(url, { type: "terminal", small: true }).then((s) => console.log(s));
    qr.toFile("data/lan-qr.png", url, { width: 900, margin: 2, color: { dark: "#0f2d3a", light: "#ffffff" } });
  ' "$URL"
  echo "QR для экрана: data/lan-qr.png (open data/lan-qr.png)"
fi
echo "Амба доступна в сети: $URL"
echo "Чтобы ноутбук не уснул во время показа: caffeinate -dis"
