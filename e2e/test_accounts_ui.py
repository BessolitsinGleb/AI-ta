"""E2E: регистрация → письмо → подтверждение → анкета → идеи → план сохранён → мои поездки → профиль."""
import re

import pytest

pw = pytest.importorskip("playwright.sync_api")
SHOTS = None  # путь для скриншотов, если нужно (см. docs/screenshots.py)


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def test_account_journey(browser, base_url):
    from app import mailer

    page = browser.new_page(viewport={"width": 1366, "height": 900})
    page.goto(f"{base_url}/#/register")
    page.fill("input[name=name]", "Саша")
    page.fill("input[name=email]", "sasha@example.com")
    page.fill("input[name=password]", "short")
    page.click("button[type=submit]")
    assert "минимум 8 символов" in page.inner_text(".form-msg")
    page.fill("input[name=password]", "Tiger2026!")
    page.click("button[type=submit]")
    page.wait_for_selector("text=Проверьте почту")

    link = re.search(r"https?://\S+", mailer.outbox[-1].text).group(0)
    page.goto(link.replace("http://localhost:8000", base_url))
    page.wait_for_selector("text=Почта подтверждена")
    assert "Саша" in page.inner_text("#account")

    page.click(".pick[data-name=interests] .chip[data-value=animals]")
    page.click(".pick[data-name=interests] .chip[data-value=sea]")
    page.click(".pick[data-name=transport] .chip[data-value=car]")
    page.click(".pick[data-name=companions] .chip[data-value=kids]")
    page.click("text=Сохранить и показать идеи")
    page.wait_for_selector(".idea")
    assert page.locator(".idea").count() >= 3 and "подходит детям" in page.inner_text(".ideas")

    page.locator(".idea .go").first.click()
    page.wait_for_selector("#result .plan h2, #questions", timeout=30000)
    if page.locator("#questions").count():
        page.click("#q-skip")
        page.wait_for_selector("#result .plan h2", timeout=30000)
    page.wait_for_selector("#toast >> text=Мои поездки")

    page.click("nav >> text=Мои поездки")
    page.wait_for_selector(".trip")
    page.click(".trip [data-fav]")
    page.wait_for_selector(".trip [data-fav][aria-pressed=true]")
    page.click(".trip-main")
    page.wait_for_selector("#saved-banner >> text=Сохранённая поездка")
    assert page.locator("#result .plan").count() == 1

    page.goto(f"{base_url}/#/profile")
    page.wait_for_selector("text=Смена пароля")
    page.fill("input[name=name]", "Александр")
    page.click("#fp button[type=submit]")
    page.wait_for_selector("#fp .form-msg.ok")
    assert "Александр" in page.inner_text("#account")

    page.reload()  # сессия переживает перезагрузку благодаря refresh-cookie
    page.wait_for_selector("#account .avatar")
    page.click("#out")
    page.wait_for_selector("#account >> text=Войти")
    page.goto(f"{base_url}/#/trips")
    page.wait_for_selector("text=Вход")
    page.close()


def test_guest_gets_hint_and_login_errors(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    page.goto(f"{base_url}/#/login")
    page.fill("input[name=email]", "nobody@example.com")
    page.fill("input[name=password]", "Wrong12345")
    page.click("button[type=submit]")
    page.wait_for_selector(".form-msg.err")
    assert "Неверная почта или пароль" in page.inner_text(".form-msg")
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    page.close()


def test_guest_must_login_before_plan(browser, base_url, monkeypatch):
    """Гость пишет запрос → вход → план собирается сам, запрос не теряется."""
    import json
    import urllib.request
    from dataclasses import replace

    from app import mailer, main

    monkeypatch.setattr(main, "settings", replace(main.settings, require_login=True))
    req = urllib.request.Request(f"{base_url}/api/auth/register", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"email": "guest@example.com", "password": "Tiger2026!", "name": "Гость"}).encode())
    urllib.request.urlopen(req)
    link = re.search(r"https?://\S+", mailer.outbox[-1].text).group(0).replace("http://localhost:8000", base_url)
    urllib.request.urlopen(link)  # почта подтверждена в стороннем «браузере» — в тестовом гость остаётся гостем

    page = browser.new_page(viewport={"width": 1366, "height": 900})
    page.goto(base_url)
    page.wait_for_selector("#guest-note:not([hidden])")
    assert page.inner_text("#submit") == "Войти и собрать план"
    page.fill("#q", "В субботу на автобусе в Находку на один день")
    page.click("#submit")
    page.wait_for_selector("#toast >> text=Запрос сохранили")
    assert "#/login" in page.url and page.locator("#result .plan").count() == 0

    page.fill("input[name=email]", "guest@example.com")
    page.fill("input[name=password]", "Tiger2026!")
    page.click("button[type=submit]")
    page.wait_for_selector("#result .plan h2, #questions", timeout=30000)
    assert page.input_value("#q").startswith("В субботу на автобусе в Находку")
    assert page.locator("#guest-note").is_hidden() and page.inner_text("#submit") == "Собрать план"
    page.close()
