import httpx
import pytest
import respx

from app import linkcheck
from app.address import format_address


@pytest.fixture(autouse=True)
def _fresh():
    linkcheck._seen.clear()


@pytest.mark.asyncio
async def test_internal_addresses_are_never_fetched():
    for url in ("http://127.0.0.1:8000/api/health", "http://169.254.169.254/latest/meta-data", "http://10.0.0.1/",
                "http://localhost/", "https://example.org:6379/", "ftp://example.org/", "file:///etc/passwd"):
        assert await linkcheck._public(url) is not True, url


@pytest.mark.asyncio
@respx.mock
async def test_link_alive_verdicts():
    respx.get("https://ok.example/").mock(return_value=httpx.Response(200))
    respx.get("https://gone.example/").mock(return_value=httpx.Response(404))
    respx.get("https://nodns.example/").mock(side_effect=httpx.ConnectError("no such host"))
    respx.get("https://busy.example/").mock(return_value=httpx.Response(503))
    got = await linkcheck.check_many(["https://ok.example/", "https://gone.example/", "https://nodns.example/", "https://busy.example/"])
    assert got == {"https://ok.example/": True, "https://gone.example/": False, "https://nodns.example/": False,
                   "https://busy.example/": None}


@pytest.mark.asyncio
@respx.mock
async def test_dead_site_links_are_removed_from_plan():
    respx.get("https://ok.example/").mock(return_value=httpx.Response(200))
    respx.get("https://gone.example/").mock(return_value=httpx.Response(410))
    plan = {"days": [{"items": [
        {"name": "Живое", "url": "https://ok.example/", "links": [{"title": "Сайт", "url": "https://ok.example/"}, {"title": "На карте", "url": "https://yandex.ru/maps/?text=a"}]},
        {"name": "Закрылось", "url": "https://gone.example/", "links": [{"title": "Сайт", "url": "https://gone.example/"}, {"title": "На карте", "url": "https://yandex.ru/maps/?text=b"}]},
    ]}]}
    assert await linkcheck.drop_dead_links(plan) == 1
    alive, gone = plan["days"][0]["items"]
    assert [x["title"] for x in alive["links"]] == ["Сайт", "На карте"] and alive["url"]
    assert [x["title"] for x in gone["links"]] == ["На карте"]  # url остаётся — по нему отметка «похоже, закрыто»


@pytest.mark.asyncio
@respx.mock
async def test_site_content_tells_if_venue_closed():
    respx.get("https://live.example/").mock(return_value=httpx.Response(200, text="<h1>Кафе «Маяк»</h1> Пн: закрыто, Вт–Вс 10–22"))
    respx.get("https://bye.example/").mock(return_value=httpx.Response(200, text="<p>Дорогие гости, мы закрылись. Спасибо!</p>"))
    respx.get("https://parked.example/").mock(return_value=httpx.Response(200, text="<title>Домен продаётся</title>"))
    respx.get("https://moved.example/").mock(return_value=httpx.Response(301, headers={"location": "https://bye.example/"}))
    respx.get("https://sneaky.example/").mock(return_value=httpx.Response(302, headers={"location": "http://127.0.0.1:6379/"}))
    assert await linkcheck.site_status("https://live.example/") == ("open", "сайт работает")  # «Пн: закрыто» — это часы
    state, why = await linkcheck.site_status("https://bye.example/")
    assert state == "closed" and "мы закрылись" in why
    assert (await linkcheck.site_status("https://parked.example/"))[0] == "closed"
    assert (await linkcheck.site_status("https://moved.example/"))[0] == "closed"  # переадресация на закрытую страницу
    assert (await linkcheck.site_status("https://sneaky.example/"))[0] == "unknown"  # во внутреннюю сеть не идём


@pytest.mark.asyncio
@respx.mock
async def test_validator_rejects_closed_venue():
    from datetime import date

    from app.intents import parse_intents
    from app.tools.base import ToolContext
    from app.validator import validate_plan

    respx.get("https://bye.example/").mock(return_value=httpx.Response(410))
    plan = {"transport": "foot", "days": [{"date": "2026-10-24", "items": [
        {"time": "11:00", "type": "place", "name": "Подлодка С-56", "place_id": "vl_s56", "lat": 43.115, "lon": 131.889},
        {"time": "13:00", "type": "food", "name": "Бывшее кафе", "lat": 43.116, "lon": 131.890, "url": "https://bye.example/"},
        {"time": "14:00", "type": "food", "name": "Кафе без сайта", "lat": 43.116, "lon": 131.890}]}]}
    ctx = ToolContext(today=date(2026, 10, 21), offline=False)
    ctx.weather["43.12,131.89"] = {"2026-10-24": {"date": "2026-10-24", "summary": "ясно", "tmin": 5, "tmax": 12, "precip_mm": 0,
                                                  "wind_max_ms": 3, "sunset": "18:15", "risks": []}}
    checks = {c.id: c for c in await validate_plan(plan, parse_intents("в субботу пешком", date(2026, 10, 21)), ctx)}
    assert not checks["venues_open"].ok and "Бывшее кафе" in checks["venues_open"].text and checks["venues_open"].severity == "error"
    assert checks["venues_unverified"].severity == "warn" and "Кафе без сайта" in checks["venues_unverified"].text


def test_address_format():
    assert format_address({"street": "Светланская улица", "housenumber": "1", "city": "Владивосток"}) == "Светланская улица, 1, Владивосток"
    assert format_address({"village": "Андреевка", "county": "Хасанский район"}) == "Андреевка"
    assert format_address({"street": "Аякс", "housenumber": "10", "locality": "Аякс"}) == "Аякс, 10"
