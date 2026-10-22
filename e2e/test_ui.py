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


def test_logbook_view(page):
    page.click(".seg-btn[data-view=logbook]")
    page.wait_for_selector(".logbook h2")
    assert "Бортовой журнал" in page.inner_text(".logbook")
    assert page.locator(".logbook .links a").count() >= 1
    page.click(".seg-btn[data-view=modern]")
    page.wait_for_selector("#result .plan")


def test_questions_then_plan_with_links(page):
    page.fill("#q", "В субботу на машине по Владивостоку, хочу вкусно поесть")
    page.click("#submit")
    page.wait_for_selector("#questions", timeout=30000)
    page.click(".q-opt[data-value='Морепродукты']")
    page.click("#questions button[type=submit]")
    page.wait_for_selector("#result .plan h2", timeout=30000)
    hrefs = page.eval_on_selector_all(".stop .links a", "els => els.map(e => e.href)")
    assert hrefs and all(h.startswith("https://") for h in hrefs)


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


def test_refine_plan_in_chat(page):
    page.goto(page.url.split("#")[0] + "#/")
    page.fill("#q", "В субботу на автобусе в Находку на один день")
    page.click("#submit")
    page.wait_for_selector("#result .plan h2", timeout=30000)
    assert page.locator("#chat").is_visible()
    page.fill("#chat-input", "давай лучше на электричке")
    page.click("#chat-form button[type=submit]")
    page.wait_for_selector("#chat-log .msg.assistant:not(.pending)", timeout=30000)
    assert page.locator("#chat-log .msg.user").count() == 1
    assert "электричк" in page.inner_text(".facts").lower()
    page.click("#chat-chips [data-say='Сделай подешевле']")
    page.wait_for_function("document.querySelectorAll('#chat-log .msg.assistant:not(.pending)').length === 2", timeout=30000)
