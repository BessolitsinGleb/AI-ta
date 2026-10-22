"""Детерминированный разбор интентов из запроса: сроки, ночёвка, транспорт, даты.

Используется валидатором и эвалом как «независимый судья»: LLM может ошибиться в интентах,
а правила — воспроизводимы.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

NUM_WORDS = {
    "один": 1, "одного": 1, "одну": 1, "одни": 1, "1": 1,
    "два": 2, "двух": 2, "две": 2, "2": 2, "пару": 2, "пара": 2,
    "три": 3, "трёх": 3, "трех": 3, "3": 3,
    "четыре": 4, "четырёх": 4, "четырех": 4, "4": 4,
    "пять": 5, "пяти": 5, "5": 5, "шесть": 6, "шести": 6, "6": 6, "семь": 7, "семи": 7, "7": 7,
}
NUM_RE = "|".join(sorted(map(re.escape, NUM_WORDS), key=len, reverse=True))

TRANSPORT_PATTERNS = [
    ("bike", r"велосипед|велик|на вело|велопрогул|велопоход|на байке"),
    ("train", r"электричк|\bпоезд(а|ом|е|у)?\b|по железной|\bжд\b|ж/д"),
    ("bus", r"автобус|общественн|маршрутк|без машины|паром"),
    ("foot", r"пешком|пешк|пеш(ий|ая|ие)|на своих двоих|хайкинг|трекинг"),
    ("car", r"машин|авто(?!бус)|автомобил|за рул|на тачке|джип"),
]

WEEKDAY_WORDS = {
    "понедельник": 0, "вторник": 1, "сред": 2, "четверг": 3, "пятниц": 4, "суббот": 5, "воскресень": 6,
}

INTEREST_WORDS = {
    "море": r"мор[ея]|бухт|побереж|остров",
    "пляж": r"пляж|купа",
    "история": r"истори|музе|крепост|батаре",
    "поход": r"поход|гор[уаы]|сопк|вершин|треккинг|водопад",
    "дети": r"с детьми|ребён|ребен|детей|семь[её]й",
    "животные": r"тигр|леопард|животн|сафари|океанариум",
    "природа": r"природ|тайг|заповедн|нацпарк|лес",
    "еда": r"морепродукт|еда|гастро|ресторан|краб|гребеш",
}


@dataclass
class Intents:
    days: int | None = None
    max_days: int | None = None
    overnight: bool | None = None
    transport: str | None = None
    weekend: bool = False
    start_date: str | None = None
    end_date: str | None = None
    interests: list[str] = field(default_factory=list)
    chips: list[str] = field(default_factory=list)

    def dict(self) -> dict:
        return asdict(self)


def _next_weekday(today: date, wd: int, allow_today: bool = True) -> date:
    delta = (wd - today.weekday()) % 7
    if delta == 0 and not allow_today:
        delta = 7
    return today + timedelta(delta)


def parse_intents(query: str, today: date) -> Intents:
    q = query.lower().replace("ё", "е")
    it = Intents()

    # Транспорт — первый найденный по приоритету списка.
    for mode, pat in TRANSPORT_PATTERNS:
        if re.search(pat, q):
            it.transport = mode
            break

    # Ограничения по длительности.
    m = re.search(rf"(не больше|не более|максимум|макс\.?|до|≤|<=)\s*({NUM_RE})\s*(дн|сут|ден)", q)
    if m:
        it.max_days = NUM_WORDS[m.group(2)]
    m = re.search(rf"\bна\s+({NUM_RE})\s*(дн|дня|сут|ден)", q) or re.search(rf"\b({NUM_RE})[- ]?(дн|дневн)", q)
    if m and not it.max_days:
        it.days = NUM_WORDS[m.group(1)]
        it.max_days = it.days
    if re.search(r"недел[юи]", q) and not it.max_days:
        it.days = it.max_days = 7
    if re.search(r"на день|однодневн|одним днем|за один день|на денек|без ночевк", q):
        it.days, it.max_days, it.overnight = 1, 1, False
    if re.search(r"с ночевк|переночев|ночевк|с ночлегом|на ночь", q) and it.overnight is None:
        it.overnight = True

    # Даты.
    start: date | None = None
    if re.search(r"выходн", q):
        it.weekend = True
        sat = _next_weekday(today, 5)
        if today.weekday() == 6:  # в воскресенье «эти выходные» — уже сегодня
            sat = today - timedelta(1)
        start = max(sat, today)
        if it.max_days is None:
            it.max_days = 2 if start == sat else 1
    elif re.search(r"послезавтра", q):
        start = today + timedelta(2)
    elif re.search(r"завтра", q):
        start = today + timedelta(1)
    elif re.search(r"сегодня", q):
        start = today
    else:
        for word, wd in WEEKDAY_WORDS.items():
            if re.search(rf"\b(в|во|на)\s+{word}", q):
                start = _next_weekday(today, wd)
                break
    if start:
        it.start_date = start.isoformat()
        length = it.days or it.max_days or (2 if it.overnight else 1)
        if it.weekend and not it.days:
            length = min(length, 2)
        it.end_date = (start + timedelta(max(length, 1) - 1)).isoformat()

    if it.overnight is None and it.max_days and it.max_days >= 2 and it.days and it.days >= 2:
        it.overnight = True

    it.interests = [name for name, pat in INTEREST_WORDS.items() if re.search(pat, q)]

    labels = {"car": "на машине", "bike": "на велосипеде", "foot": "пешком", "bus": "на автобусе", "train": "на поезде"}
    if it.weekend:
        it.chips.append("на выходные")
    if it.days:
        it.chips.append(f"{it.days} дн.")
    if it.overnight:
        it.chips.append("с ночёвкой")
    if it.overnight is False:
        it.chips.append("без ночёвки")
    if it.max_days and it.max_days != it.days:
        it.chips.append(f"≤ {it.max_days} дн.")
    if it.transport:
        it.chips.append(labels[it.transport])
    it.chips.extend(it.interests)
    it.chips.append("Приморье")
    return it


def merge_intents(base: Intents, change: Intents) -> Intents:
    """Интенты уточнения поверх исходного запроса: «давай на автобусе» меняет транспорт, остальное остаётся."""
    merged = Intents(**base.dict())
    for f in ("days", "max_days", "overnight", "transport", "start_date", "end_date"):
        val = getattr(change, f)
        if val is not None:
            setattr(merged, f, val)
    merged.weekend = base.weekend or change.weekend
    merged.interests = sorted(set(base.interests) | set(change.interests))
    merged.chips = list(dict.fromkeys(base.chips[:-1] + [c for c in change.chips if c != "Приморье"] + ["Приморье"]))
    return merged
