from datetime import date

import pytest

from app.intents import parse_intents

WED = date(2026, 10, 21)  # среда


def test_weekend_resolves_to_next_saturday_sunday():
    it = parse_intents("Хочу на эти выходные поездить по Уралу с ночёвкой, не больше двух дней", WED)
    assert it.weekend and it.overnight
    assert it.max_days == 2
    assert (it.start_date, it.end_date) == ("2026-10-24", "2026-10-25")
    assert {"на выходные", "с ночёвкой", "≤ 2 дн."} <= set(it.chips)


def test_weekend_on_sunday_is_today_only():
    it = parse_intents("куда на выходные?", date(2026, 10, 25))
    assert it.start_date == "2026-10-25" and it.max_days == 1


@pytest.mark.parametrize("text, mode", [
    ("поездить по Приморью на машине", "car"),
    ("хочу поездить по краю на велосипеде", "bike"),
    ("на электричке в Уссурийск", "train"),
    ("на поезде до Находки", "train"),
    ("на автобусе в Находку", "bus"),
    ("пешком по центру", "foot"),
    ("хочу поездить по Приморью", None),  # «поездить» — не поезд
])
def test_transport(text, mode):
    assert parse_intents(text, WED).transport == mode


def test_one_day_without_overnight():
    it = parse_intents("в субботу на один день", WED)
    assert it.max_days == 1 and it.days == 1
    assert it.start_date == "2026-10-24"


def test_day_trip_phrase():
    it = parse_intents("Еломовские водопады на день", WED)
    assert it.days == 1 and it.overnight is False


def test_n_days_and_week():
    assert parse_intents("на 3 дня в Хасан", WED).max_days == 3
    assert parse_intents("неделю на Ханке", WED).max_days == 7


def test_tomorrow_and_interests():
    it = parse_intents("Завтра с детьми в океанариум и к тиграм", WED)
    assert it.start_date == "2026-10-22"
    assert {"дети", "животные"} <= set(it.interests)
