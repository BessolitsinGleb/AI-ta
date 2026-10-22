import assert from "node:assert/strict";
import { test } from "node:test";
import { esc, fuelBadges, humanDate, linksHtml, renderLogbook, renderNotice, renderPlan, renderQuestions, renderTraceLine, weatherIcon } from "../js/render.js";

const result = {
  status: "plan",
  model: "openai/gpt-4.1-mini",
  sources: ["Open-Meteo", "OSRM (OpenStreetMap)"],
  metrics: { latency_s: 12.3, total_tokens: 8412, cost_usd: 0.0041, llm_calls: 4 },
  check_summary: { passed: 2, total: 3, converges: false },
  checks: [
    { id: "days_limit", ok: true, text: "Дней в плане: 2" },
    { id: "weather", ok: false, severity: "error", text: "Погода: дождь" },
    { id: "known_places", ok: false, severity: "warn", text: "Место не из базы" },
  ],
  plan: {
    title: "Находка и гора Сестра", zachin: "Гой еси, путник!", summary: "Один день", transport: "bus",
    cautions: ["Последний автобус в 18:00"],
    days: [{ date: "2026-10-24", title: "Находка", weather: { summary: "ясно", tmin: 4, tmax: 12, precip_mm: 0, risks: [] },
      items: [{ time: "08:30", type: "transfer", name: "Автобус", trip_id: "bus_vl_nk:there" },
        { time: "12:00", type: "place", name: "Гора <Сестра>", details: "Подъём" }],
      lodging: { name: "Отель", price_rub: 4800 } }],
  },
};

test("бортовой журнал: заголовок, координаты, ссылки, печать, без старорусского", () => {
  const html = renderLogbook(result);
  assert.match(html, /Бортовой журнал/);
  assert.match(html, /Суббота, 24 октября/);
  assert.match(html, /lb-stamp bad/);
  assert.match(html, /Перед выходом/);
  assert.ok(!html.includes("<Сестра>"));
  assert.ok(!/ъ\b|ѣ/.test(html.replace(/<[^>]+>/g, "")));
});

test("ссылки: только https, открываются в новой вкладке", () => {
  const html = linksHtml([{ title: "На карте", url: "https://yandex.ru/maps/?text=x" }, { title: "Плохая", url: "javascript:alert(1)" }]);
  assert.match(html, /target="_blank" rel="noopener noreferrer"/);
  assert.ok(!html.includes("javascript"));
  assert.equal(linksHtml([]), "");
});

test("вопросы: варианты ответа и пропуск", () => {
  const html = renderQuestions({ questions: [{ text: "Какая кухня?", options: ["Морепродукты", "Корейская"] }] });
  assert.match(html, /Пара уточнений/);
  assert.match(html, /data-value="Морепродукты"/);
  assert.match(html, /id="q-skip"/);
});

test("строки летописи трудов", () => {
  assert.match(renderTraceLine({ type: "tool", name: "get_weather" }), /Смотрю прогноз погоды/);
  assert.match(renderTraceLine({ type: "tool_result", summary: "<b>x</b>" }), /&lt;b&gt;/);
  assert.match(renderTraceLine({ type: "check", summary: { passed: 3, total: 4, converges: false }, failed: ["дождь"] }), /tr-check bad/);
  assert.equal(renderTraceLine({ type: "unknown" }), "");
  assert.equal(esc(`<a href="x">'`), "&lt;a href=&quot;x&quot;&gt;&#39;");
});

test("современный план: факты, сверка, дни, ночёвка, что учесть, подвал", () => {
  const html = renderPlan(result);
  assert.match(html, /Находка и гора Сестра/);
  assert.match(html, /Суббота, 24 октября/);
  assert.match(html, /На автобусе/);
  assert.match(html, /class="verify bad" open/);
  assert.match(html, /Есть противоречия: 1 из 3/);
  assert.match(html, /Ночёвка:<\/span> Отель/);
  assert.match(html, /4\s800 ₽ за ночь/);
  assert.match(html, /Что учесть/);
  assert.match(html, /Собран за 12,3 с/);
  assert.ok(!html.includes("<Сестра>"), "HTML экранируется");
  assert.ok(!/ъ\b/.test(html.replace(/<[^>]+>/g, "")), "без дореформенной орфографии");
});

test("сходящийся план свёрнут, отказ и ошибка", () => {
  const ok = renderPlan({ ...result, checks: [{ id: "a", ok: true, text: "ок" }], check_summary: { passed: 1, total: 1, converges: true } });
  assert.match(ok, /class="verify ok">/);
  assert.match(ok, /План сходится: пройдено 1 проверок из 1/);
  const refusal = renderNotice({ status: "declined", refusal: { category: "other_region", message: "Не Приморье", by: "prefilter" } }, "<svg></svg>");
  assert.match(refusal, /Это не Приморский край/);
  assert.match(refusal, /0 токенов/);
  assert.match(renderNotice({ status: "error", error: "OpenRouter 402" }), /Не получилось собрать план[\s\S]*402/);
});

test("даты и значки погоды", () => {
  assert.equal(humanDate("2026-10-24"), "Суббота, 24 октября");
  assert.equal(weatherIcon("небольшой дождь"), "🌧");
  assert.equal(weatherIcon("ясно"), "☀");
  assert.equal(weatherIcon("туман"), "🌫");
});

test("демо-режим: не показываем оценку токенов как расход", () => {
  const html = renderPlan({ ...result, metrics: { latency_s: 1, total_tokens: 3000, cost_usd: 0, estimated: true } });
  assert.match(html, /расход токенов не считается/);
  assert.ok(!/3\s000 токенов/.test(html));
});

test("план связан с картой: день — фокус, точка с координатами — метка", () => {
  const withCoords = structuredClone(result);
  withCoords.plan.days[0].items[1] = { ...withCoords.plan.days[0].items[1], lat: 42.8, lon: 132.9 };
  const html = renderPlan(withCoords);
  assert.match(html, /data-focus-day="0"/);
  assert.match(html, /data-map-day="0" data-map-item="1"/);
  assert.doesNotMatch(html, /data-map-item="0"/);  // у автобуса нет координат — на карту не ведёт
  assert.doesNotMatch(html, /data-map-item="lodging"/);
});

test("очередь и АЗС: честные подписи", () => {
  assert.match(renderTraceLine({ type: "queued" }), /много запросов/);
  const html = fuelBadges({ "АИ-92": true, "АИ-95": null, "ДТ": false, "Газ": true });
  assert.match(html, /fuel yes[^>]*>АИ-92/);
  assert.match(html, /fuel unk[^>]*title="АИ-95: в OSM не указано"/);
  assert.match(html, /fuel no[^>]*>ДТ/);
  assert.match(html, />Газ</);
});

