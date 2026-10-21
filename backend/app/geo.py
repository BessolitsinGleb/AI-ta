"""Геометрия: расстояния и границы Приморского края."""
from __future__ import annotations

import math

# Грубый охватывающий прямоугольник Приморского края (с запасом на острова и побережье).
PRIMORYE_BBOX = (42.2, 130.3, 48.6, 139.2)  # south, west, north, east


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def in_primorye(lat: float, lon: float) -> bool:
    s, w, n, e = PRIMORYE_BBOX
    if not (s <= lat <= n and w <= lon <= e):
        return False
    # Отсекаем северо-запад прямоугольника (Хабаровский край / Китай): граница идёт по диагонали.
    if lat > 46.3 and lon < 133.0:
        return False
    if lat > 47.4 and lon < 135.5:
        return False
    return True


def path_length_km(points: list[tuple[float, float]]) -> float:
    return sum(haversine_km(*points[i], *points[i + 1]) for i in range(len(points) - 1))
