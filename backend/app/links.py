"""Ссылки, по которым человек сам всё оформит: карты, расписания и билеты, жильё."""
from __future__ import annotations

from urllib.parse import quote, urlencode

RASP_KIND = {"bus": "bus", "train": "suburban", "ferry": "water"}


def yandex_maps(text: str, lat: float | None = None, lon: float | None = None, zoom: int = 16) -> str:
    params = {"text": text}
    if lat is not None and lon is not None:
        params.update({"ll": f"{lon:.5f},{lat:.5f}", "z": str(zoom)})
    return "https://yandex.ru/maps/?" + urlencode(params)


def rasp(src: str, dst: str, day: str, kind: str = "bus") -> str:
    path = RASP_KIND.get(kind, "all")
    return f"https://rasp.yandex.ru/search/{path}/?" + urlencode({"fromName": src, "toName": dst, "when": day})


def wiki(title: str) -> str:
    return "https://ru.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))
