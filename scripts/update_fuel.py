"""Снимок АЗС Приморья из OpenStreetMap → backend/app/data/fuel_osm.json.

    .venv/bin/python scripts/update_fuel.py        (или make fuel-data)

Overpass на запрос по всему краю отвечает за полминуты и часто перегружен — в момент планирования его не ждём,
а берём этот снимок. Обновлять раз в неделю-месяц: АЗС открываются и закрываются нечасто.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import settings  # noqa: E402
from app.tools.fuel import OVERPASS, SNAPSHOT, station_info  # noqa: E402

QUERY = ('[out:json][timeout:120];area["ISO3166-2"="RU-PRI"]->.pk;'
         '(node["amenity"="fuel"](area.pk);way["amenity"="fuel"](area.pk););out center tags;')


def main() -> None:
    resp = httpx.post(OVERPASS, data={"data": QUERY}, timeout=150, headers={"User-Agent": settings.user_agent})
    resp.raise_for_status()
    data = resp.json()
    stations = [station_info(el) for el in data["elements"] if el.get("lat") or el.get("center")]
    out = {"source": "OpenStreetMap (© участники OSM, ODbL)", "osm_timestamp": data.get("osm3s", {}).get("timestamp_osm_base"),
           "stations": stations}
    SNAPSHOT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    known = sum(any(v is not None for v in s["fuel"].values()) for s in stations)
    print(f"{len(stations)} АЗС, у {known} известно топливо → {SNAPSHOT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
