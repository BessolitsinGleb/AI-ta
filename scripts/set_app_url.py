"""Перевести ссылки и QR «Приложение» на новый адрес: сайт команды, визитка, презентация.

    .venv/bin/python scripts/set_app_url.py http://192.168.1.5:8000

scripts/lan.sh вызывает его сам: IP ноутбука меняется вместе с сетью. Сайт команды живёт на GitHub Pages,
поэтому после смены адреса его нужно опубликовать: make publish-site.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs" / "site" / "index.html"
SITE_QR = ROOT / "docs" / "site" / "assets" / "qr-app.svg"
CARD = ROOT / "docs" / "card" / "amba-card-back.svg"
# копия визитки там, где её делали (если папка есть на этом компьютере)
CARD_COPY = Path.home() / "Documents/Codex/2026-10-22/railway-docker-docker-desktop-git-git/outputs/amba-card-back.svg"

# прежние адреса приложения: облако (Render, Railway) или http://IP:порт ноутбука
HOSTED = r"amba[\w-]*\.(?:onrender\.com|up\.railway\.app)"
OLD_URL = rf"(?:https://{HOSTED}|http://\d{{1,3}}(?:\.\d{{1,3}}){{3}}:\d+)/?"
OLD_SHOWN = rf"(?:(?:https://)?{HOSTED}|http://\d{{1,3}}(?:\.\d{{1,3}}){{3}}:\d+)"


def qr_svg(url: str) -> str:
    out = subprocess.run(
        ["node", "-e", "require('qrcode').toString(process.argv[1], {type: 'svg', margin: 1, "
         "color: {dark: '#0f2d3a', light: '#ffffff'}}).then((s) => process.stdout.write(s))", url],
        cwd=ROOT / "presentation", check=True, capture_output=True, text=True)
    svg = out.stdout.strip()
    vb = re.search(r'viewBox="([^"]+)"', svg).group(1)
    inner = svg[svg.index(">", svg.index("<svg")) + 1: svg.rindex("</svg>")]
    return vb, inner


def sub_all(pattern: str, repl: str, text: str, where: str) -> str:
    new, n = re.subn(pattern, lambda _: repl, text)
    if not n:
        raise SystemExit(f"{where}: не нашёл адрес приложения")
    return new


def main(url: str) -> None:
    # подпись под QR: облачный адрес без https://, адрес ноутбука — целиком, с http://
    shown = url.rstrip("/").removeprefix("https://")
    vb, inner = qr_svg(url)

    html = SITE.read_text(encoding="utf-8")
    html = sub_all(rf'href="{OLD_URL}"', f'href="{url}"', html, "сайт: ссылки")
    html = sub_all(rf'(?<=<span class="qr-url">){OLD_SHOWN}(?=</span>)', shown, html, "сайт: подпись QR")
    SITE.write_text(html, encoding="utf-8")
    SITE_QR.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" shape-rendering="crispEdges">{inner}</svg>\n', encoding="utf-8")

    for card in (CARD, CARD_COPY):
        if not card.exists():
            continue
        svg = card.read_text(encoding="utf-8")
        svg = sub_all(r'<svg x="564" y="446" width="88" height="88" viewBox="[^"]+" shape-rendering="crispEdges">.*?</svg>',
                      f'<svg x="564" y="446" width="88" height="88" viewBox="{vb}" shape-rendering="crispEdges">{inner}</svg>',
                      svg.replace("\n", "\x00"), f"{card.name}: QR").replace("\x00", "\n")
        svg = sub_all(rf'(?<=class="muted">){OLD_SHOWN}(?=</text>)', shown, svg, f"{card.name}: подпись")
        card.write_text(svg, encoding="utf-8")

    sys.path.insert(0, str(ROOT / "presentation"))
    from set_app_qr import main as deck_qr  # noqa: E402 — QR на слайде 11 + PDF

    deck_qr(url)
    print("Приложение →", url, "(сайт, визитка, презентация)")


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].startswith(("http://", "https://")):
        sys.exit("укажите адрес: set_app_url.py http://<IP>:8000")
    main(sys.argv[1])
