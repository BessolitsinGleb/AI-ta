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
NUM_RE = "|".join(sorted(map(re.escape, NUM_WORDS), key=len, reverse=True)) + r"|\d{1,2}"
MONTHS = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма[йя]": 5, "июн": 6, "июл": 7, "август": 8,
          "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}
MONTH_RE = "(" + "|".join(MONTHS) + r")[а-я]*"


def _num(s: str) -> int:
    return NUM_WORDS.get(s) or int(s)


def _month(word: str) -> int:
    return next(n for stem, n in MONTHS.items() if re.match(stem, word))


def _on_or_after(today: date, month: int, day: int) -> date | None:
    """«29 октября» — ближайшее такое число: в этом году или, если уже прошло, в следующем."""
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d >= today - timedelta(1):
            return d
    return None


def explicit_dates(q: str, today: date) -> tuple[date, date] | None:
    """Календарные даты: «с 30 октября по 2 ноября», «1-3 ноября», «29 октября», «24.10»."""
    sep = r"\s*(?:-|–|—|по|до)\s*"
    m = re.search(rf"(\d{{1,2}})\s+{MONTH_RE}{sep}(\d{{1,2}})\s+{MONTH_RE}", q)
    if m:
        a = _on_or_after(today, _month(m.group(2)), int(m.group(1)))
        b = a and _on_or_after(a, _month(m.group(4)), int(m.group(3)))
        return (a, b) if a and b else None
    m = re.search(rf"(\d{{1,2}}){sep}(\d{{1,2}})\s+{MONTH_RE}", q)
    if m:
        mon = _month(m.group(3))
        a = _on_or_after(today, mon, int(m.group(1)))
        b = a and _on_or_after(a, mon, int(m.group(2)))
        return (a, b) if a and b else None
    m = re.search(rf"(\d{{1,2}})\s+{MONTH_RE}", q) or re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.\d{2,4})?\b", q)
    if m:
        mon = _month(m.group(2)) if not m.group(2).isdigit() else int(m.group(2))
        d = _on_or_after(today, mon, int(m.group(1))) if 1 <= mon <= 12 else None
        return (d, d) if d else None
    return None

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
        it.max_days = _num(m.group(2))
    m = re.search(rf"\bна\s+({NUM_RE})\s*(дн|дня|сут|ден)", q) or re.search(rf"\b({NUM_RE})[- ]?(дн|дневн)", q)
    if m and not it.max_days:
        it.days = _num(m.group(1))
        it.max_days = it.days
    if re.search(r"недел[юи]", q) and not it.max_days:
        it.days = it.max_days = 7
    if re.search(r"на день|однодневн|одним днем|за один день|на денек|без ночевк", q):
        it.days, it.max_days, it.overnight = 1, 1, False
    if re.search(r"с ночевк|переночев|ночевк|с ночлегом|на ночь", q) and it.overnight is None:
        it.overnight = True

    # Даты: сначала календарные, потом относительные слова.
    start: date | None = None
    span = explicit_dates(q, today)
    if span:
        start, end = span
        if end > start:
            it.days = it.max_days = (end - start).days + 1
            if it.overnight is None:
                it.overnight = True
    elif re.search(r"выходн", q):
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
        named = sorted((m.start(), wd) for word, wd in WEEKDAY_WORDS.items() for m in re.finditer(rf"\b(?:в|во|на|и)\s+{word}", q))
        if named and re.search(r"\b(в|во|на)\s+", q[named[0][0]:named[0][0] + 3]):
            start = _next_weekday(today, named[0][1])
            if len(named) > 1:  # «в субботу и воскресенье» — до последнего названного дня
                last = start + timedelta((named[-1][1] - named[0][1]) % 7)
                if last > start and it.days is None:
                    it.days = it.max_days = (last - start).days + 1
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
