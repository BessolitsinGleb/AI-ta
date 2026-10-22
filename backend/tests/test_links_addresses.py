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
    assert [x["title"] for x in gone["links"]] == ["На карте"] and "url" not in gone


def test_address_format():
    assert format_address({"street": "Светланская улица", "housenumber": "1", "city": "Владивосток"}) == "Светланская улица, 1, Владивосток"
    assert format_address({"village": "Андреевка", "county": "Хасанский район"}) == "Андреевка"
    assert format_address({"street": "Аякс", "housenumber": "10", "locality": "Аякс"}) == "Аякс, 10"
