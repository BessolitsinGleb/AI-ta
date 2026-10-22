"""Рекомендации по анкете интересов и истории поездок — без LLM, бесплатно и мгновенно."""
from __future__ import annotations

from .links import yandex_maps
from .tools.base import load_data

INTERESTS = {  # ключ анкеты → подпись и теги мест в датасете
    "sea": ("Море и пляжи", {"море", "пляж", "купание"}),
    "history": ("История и музеи", {"история", "музей", "культура", "флот"}),
    "hiking": ("Походы и горы", {"поход", "гора", "водопад", "скалы"}),
    "animals": ("Животные", {"животные", "тигр", "леопард"}),
    "nature": ("Природа и заповедники", {"природа", "озеро", "река", "тисовая роща"}),
    "food": ("Еда и морепродукты", {"еда"}),
    "views": ("Виды и фото", {"вид", "фото", "архитектура"}),
}
TRANSPORT = {"car": "На машине", "public": "Автобус и электричка", "bike": "Велосипед", "foot": "Пешком"}
COMPANIONS = {"solo": "Один", "couple": "Вдвоём", "friends": "С друзьями", "kids": "С детьми"}
BUDGET = {"low": "Экономно", "mid": "Средне", "high": "С комфортом"}
PACE = {"calm": "Спокойно", "balanced": "Сбалансированно", "active": "Активно"}

IDEAS = [
    {"id": "russky", "title": "Остров Русский за день", "emoji": "🌉", "area": "остров Русский", "days": 1,
     "interests": {"sea", "views", "animals"}, "transport": {"public", "car", "bike"}, "kids": True, "pace": "calm",
     "query": "Завтра на остров Русский: океанариум, Русский мост и мыс Тобизина"},
    {"id": "center", "title": "Исторический центр Владивостока пешком", "emoji": "🏛️", "area": "Владивосток", "days": 1,
     "interests": {"history", "views", "food"}, "transport": {"foot", "public"}, "kids": True, "pace": "calm",
     "query": "В субботу пешком по центру Владивостока: крепость, подлодка С-56, фуникулёр и виды"},
    {"id": "khasan", "title": "Хасан: бухта Витязь и «Земля леопарда»", "emoji": "🐆", "area": "Хасанский район", "days": 3,
     "interests": {"sea", "nature", "animals", "hiking"}, "transport": {"car"}, "kids": True, "pace": "balanced", "budget": "mid",
     "query": "На 3 дня на машине в Хасанский район с ночёвкой: бухта Витязь, маяк Гамова и «Земля леопарда»"},
    {"id": "safari", "title": "Тигры в сафари-парке", "emoji": "🐯", "area": "Шкотовский район", "days": 1,
     "interests": {"animals", "nature"}, "transport": {"car", "public"}, "kids": True, "pace": "calm",
     "query": "В воскресенье в Приморский сафари-парк к тиграм, вернуться вечером"},
    {"id": "sestra", "title": "Находка и гора Сестра", "emoji": "⛰️", "area": "Находка", "days": 1,
     "interests": {"hiking", "views", "sea"}, "transport": {"public", "car"}, "kids": False, "pace": "active", "budget": "low",
     "query": "В субботу на автобусе в Находку на один день, подняться на гору Сестра"},
    {"id": "ussuriysk", "title": "Уссурийск на электричке", "emoji": "🚆", "area": "Уссурийск", "days": 1,
     "interests": {"history"}, "transport": {"public"}, "kids": True, "pace": "calm", "budget": "low",
     "query": "Завтра на электричке в Уссурийск: собор, каменная черепаха и музей, вернуться вечером"},
    {"id": "khanka", "title": "Озеро Ханка: пляжи и лотосы", "emoji": "🪷", "area": "Ханкайский район", "days": 2,
     "interests": {"nature", "sea"}, "transport": {"car"}, "kids": True, "pace": "calm", "budget": "mid",
     "query": "На выходные на машине на озеро Ханка с ночёвкой"},
    {"id": "falls", "title": "Еломовские водопады", "emoji": "💧", "area": "Шкотовский район", "days": 1,
     "interests": {"hiking", "nature", "views"}, "transport": {"car"}, "kids": False, "pace": "active",
     "query": "В воскресенье на машине к Еломовским водопадам, туда и обратно за день"},
    {"id": "pidan", "title": "Гора Пидан с ночёвкой", "emoji": "🏕️", "area": "Партизанский район", "days": 2,
     "interests": {"hiking", "nature", "views"}, "transport": {"car"}, "kids": False, "pace": "active",
     "query": "На выходные в поход на гору Пидан с ночёвкой, на машине"},
    {"id": "petrova", "title": "Лазо и остров Петрова", "emoji": "🌲", "area": "Лазовский район", "days": 3,
     "interests": {"nature", "sea", "animals"}, "transport": {"car"}, "kids": True, "pace": "balanced", "budget": "mid",
     "query": "Поездка в Лазо и на остров Петрова на 3 дня на машине с ночёвками"},
    {"id": "gastro", "title": "Гастро-день во Владивостоке", "emoji": "🦀", "area": "Владивосток", "days": 1,
     "interests": {"food", "views"}, "transport": {"foot", "public"}, "kids": True, "pace": "calm",
     "query": "В субботу пешком по Владивостоку: морепродукты, набережная и закат на Орлином гнезде"},
    {"id": "bike", "title": "Велопрогулка по острову Русский", "emoji": "🚲", "area": "остров Русский", "days": 1,
     "interests": {"sea", "views", "nature"}, "transport": {"bike"}, "kids": False, "pace": "active",
     "query": "Завтра велопрогулка по острову Русский на полдня"},
    {"id": "sikhote", "title": "Сихотэ-Алинь и Терней", "emoji": "🦌", "area": "Тернейский район", "days": 3,
     "interests": {"nature", "animals", "hiking"}, "transport": {"car"}, "kids": False, "pace": "active", "budget": "high",
     "query": "На 3 дня на машине в Терней к Сихотэ-Алинскому заповеднику с ночёвками"},
]


def recommend_trips(profile: dict, recent_areas: list[str] | None = None, limit: int = 6) -> list[dict]:
    interests = set(profile.get("interests") or [])
    transport = set(profile.get("transport") or [])
    kids = profile.get("companions") == "kids"
    recent = {a.lower() for a in (recent_areas or [])}
    scored = []
    for idea in IDEAS:
        match = interests & idea["interests"]
        score = 3 * len(match)
        if transport and transport & idea["transport"]:
            score += 2
        elif transport:
            score -= 3  # нужен транспорт, которым человек не пользуется
        if kids:
            score += 2 if idea["kids"] else -4
        if profile.get("pace") and profile["pace"] == idea["pace"]:
            score += 1
        if profile.get("budget") == "low" and idea["days"] > 1 and "car" in idea["transport"] and len(idea["transport"]) == 1:
            score -= 1
        if idea["area"].lower() in recent:
            score -= 2  # туда недавно уже планировали — предлагаем новое
        why = [INTERESTS[k][0].lower() for k in sorted(match)]
        if transport & idea["transport"]:
            why.append(TRANSPORT[sorted(transport & idea["transport"])[0]].lower())
        if kids and idea["kids"]:
            why.append("подходит детям")
        scored.append((score, idea, why))
    scored.sort(key=lambda t: -t[0])
    return [{"id": i["id"], "title": i["title"], "emoji": i["emoji"], "area": i["area"], "days": i["days"],
             "query": i["query"], "why": why, "score": s} for s, i, why in scored[:limit]]


def recommend_places(profile: dict, limit: int = 6) -> list[dict]:
    tags = set().union(*(INTERESTS[k][1] for k in profile.get("interests") or [] if k in INTERESTS)) or {"вид", "море"}
    kids = profile.get("companions") == "kids"
    rows = []
    for p in load_data("places.json"):
        s = len(tags & set(p["tags"])) + (1 if kids and "дети" in p["tags"] else 0)
        if s:
            rows.append((s, p))
    rows.sort(key=lambda t: -t[0])
    return [{"id": p["id"], "name": p["name"], "area": p["area"], "desc": p["desc"],
             "map_url": yandex_maps(p["name"], p["lat"], p["lon"])} for _, p in rows[:limit]]


def options() -> dict:
    """Варианты ответов для анкеты — фронт рисует её по этим данным."""
    return {"interests": {k: v[0] for k, v in INTERESTS.items()}, "transport": TRANSPORT,
            "companions": COMPANIONS, "budget": BUDGET, "pace": PACE}
