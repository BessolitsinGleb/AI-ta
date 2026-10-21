import assert from "node:assert/strict";
import { test } from "node:test";
import { esc, humanDate, renderChecks, renderManuscript, renderNotice, renderPlan, renderRefusal, renderTraceLine, weatherIcon } from "../js/render.js";

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

test("грамота: заголовок, буквица, главы, ночлег, метрики, источники", () => {
  const html = renderManuscript(result, { old: true, now: new Date("2026-10-21T12:00:00") });
  assert.match(html, /class="bukvitsa"[^>]*>Г</);
  assert.match(html, /Глава<\/span><span class="ms-glava-num"><span class="cyr-num"/);
  assert.match(html, /Ночлегъ/);
  assert.match(html, /4\s800 ₽/);
  assert.match(html, /рейсъ bus_vl_nk/);
  assert.match(html, /8\s412 токенов/);
  assert.match(html, /Источники: Open-Meteo/);
  assert.match(html, /Что вѣдать надобно/);
  assert.ok(!html.includes("<Сестра>"), "HTML экранируется");
});

test("современный вид без дореформенной орфографии", () => {
  const html = renderManuscript(result, { old: false });
  assert.match(html, /Что учесть/);
  assert.match(html, /Ночёвка/);
  assert.ok(!html.includes("путникъ"));
});

test("печать сверки: противоречия, предупреждения", () => {
  const html = renderChecks(result.checks, result.check_summary);
  assert.match(html, /ms-check bad/);
  assert.match(html, /ms-check warn/);
  assert.match(html, /ms-seal bad/);
});

test("отказ пред-фильтром — без токенов", () => {
  const html = renderRefusal({ status: "declined", refusal: { category: "other_region", message: "Не Приморье", by: "prefilter" } });
  assert.match(html, /Земли сіи мнѣ невѣдомы/);
  assert.match(html, /0 токенов/);
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
