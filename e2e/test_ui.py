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


def test_request_to_plan(page):
    page.fill("#q", "В субботу на автобусе в Находку на один день")
    page.click("#submit")
    page.wait_for_selector("#result .plan h2", timeout=30000)
    assert page.locator(".intent").count() >= 3
    assert page.locator(".trace li").count() >= 4  # шаги агента пришли по SSE
    assert page.locator(".day").count() == 1
    assert "План сходится" in page.inner_text(".verify summary")
    assert page.locator("#old-wrap").is_hidden()
    assert page.locator("#map .leaflet-overlay-pane path").count() >= 1  # маршрут на карте


def test_manuscript_view_and_orthography(page):
    page.click(".seg-btn[data-view=manuscript]")
    page.wait_for_selector(".scroll .ms-title")
    assert page.locator(".ms-seal").is_visible()
    assert "ъ" in page.inner_text(".ms-zachin")
    page.uncheck("#old")
    assert "Что учесть" in page.inner_text("#result")
    page.check("#old")
    assert "Что вѣдать надобно" in page.inner_text("#result")
    page.click(".seg-btn[data-view=modern]")
    page.wait_for_selector("#result .plan")


def test_refusal(page):
    page.fill("#q", "Спланируй неделю в Сочи")
    page.click("#submit")
    page.wait_for_selector(".refusal", timeout=15000)
    assert "не Приморский край" in page.inner_text(".refusal")
    assert page.locator(".notice-art.sad").count() == 1


def test_mobile_has_no_horizontal_scroll(browser, base_url):
    page = browser.new_page(viewport={"width": 375, "height": 812})
    page.goto(base_url)
    page.fill("#q", "Пешком по Владивостоку завтра")
    page.click("#submit")
    page.wait_for_selector("#result .plan", timeout=30000)
    assert page.evaluate("document.documentElement.scrollWidth") <= 375
    page.close()
