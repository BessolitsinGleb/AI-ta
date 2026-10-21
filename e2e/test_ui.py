"""E2E: настоящий браузер (Playwright/Chromium) проходит путь от запроса до грамоты."""
import pytest

pw = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(scope="module")
def page(browser, base_url):
    page = browser.new_page(viewport={"width": 1366, "height": 900})
    page.goto(base_url)
    yield page
    page.close()


def test_request_to_manuscript(page):
    page.fill("#q", "В субботу на автобусе в Находку на один день")
    page.click("#submit")
    page.wait_for_selector(".scroll .ms-title", timeout=30000)
    assert page.locator(".intent").count() >= 3
    assert page.locator(".trace li").count() >= 4  # летопись трудов агента пришла по SSE
    assert page.locator(".ms-day").count() == 1
    assert page.locator(".ms-seal").is_visible()
    assert "ъ" in page.inner_text(".ms-zachin")
    assert page.locator("#map .leaflet-overlay-pane path").count() >= 1  # маршрут на карте


def test_orthography_toggle(page):
    page.uncheck("#old")
    assert "Что учесть" in page.inner_text("#result")
    page.check("#old")
    assert "Что вѣдать надобно" in page.inner_text("#result")


def test_refusal(page):
    page.fill("#q", "Спланируй неделю в Сочи")
    page.click("#submit")
    page.wait_for_selector(".refusal", timeout=15000)
    assert "невѣдомы" in page.inner_text(".refusal")
    assert page.locator(".loading-art.sad").count() == 1


def test_mobile_has_no_horizontal_scroll(browser, base_url):
    page = browser.new_page(viewport={"width": 375, "height": 812})
    page.goto(base_url)
    page.fill("#q", "Пешком по Владивостоку завтра")
    page.click("#submit")
    page.wait_for_selector(".scroll .ms-title", timeout=30000)
    assert page.evaluate("document.documentElement.scrollWidth") <= 375
    page.close()
