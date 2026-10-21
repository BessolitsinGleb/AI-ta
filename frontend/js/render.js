// Рендер ответа агента в виде старорусской грамоты. Чистые функции → HTML-строки (тестируются в Node).
import { colophon, cyrillicNumeral, oldDate, ORDINALS, toOldOrthography } from "./oldstyle.js";

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

const t = (text, old) => esc(old ? toOldOrthography(text) : text);

export const TOOL_LABELS = {
  search_places: "Ищу места",
  get_weather: "Смотрю прогноз погоды — Open-Meteo",
  build_route: "Строю маршрут — OSRM",
  find_fuel_stations: "Проверяю заправки по пути",
  find_lodging: "Ищу ночёвку",
  public_transport: "Смотрю расписание транспорта",
  find_events: "Ищу события на эти даты",
  geocode: "Ищу точку на карте — Nominatim",
  place_info: "Читаю справку в Википедии",
  submit_plan: "Собираю план",
  decline_request: "Отказываю: запрос не по теме",
  precheck: "Фильтр запросов",
  validate_plan: "Проверка плана",
};

const GLYPH = { place: "❖", transfer: "➳", food: "♨", lodging: "☾", note: "✎" };
const TRANSPORT = { car: "на машинѣ", bike: "на велосипедѣ", foot: "пѣшкомъ", bus: "на автобусѣ", train: "на поѣздѣ" };

export function weatherLine(w, old = true) {
  if (!w) return "";
  const temp = w.tmin != null && w.tmax != null ? `${Math.round(w.tmin)}…${Math.round(w.tmax)}°` : "";
  const parts = [w.summary, temp, w.precip_mm != null ? `осадки ${w.precip_mm} мм` : "", w.wind_max_ms != null ? `вѣтеръ ${Math.round(w.wind_max_ms)} м/с` : "",
    w.sunset ? `закатъ ${w.sunset}` : ""].filter(Boolean);
  const risk = (w.risks || []).length ? ` <b class="ms-risk">⚠ ${t(w.risks.join(", "), old)}</b>` : "";
  return `<div class="ms-weather"><span class="ms-weather-label">${old ? "Небесныя знаменія" : "Погода"}:</span> ${t(parts.join(" · "), old)}${risk}</div>`;
}

export function renderItem(it, old = true) {
  const glyph = GLYPH[it.type] || "•";
  const meta = [];
  if (it.trip_id) meta.push(`<span class="ms-tag">рейсъ ${esc(it.trip_id.split(":")[0])}</span>`);
  return `<li class="ms-item type-${esc(it.type || "note")}">
    <span class="ms-time">${esc(it.time || "")}</span>
    <span class="ms-glyph" aria-hidden="true">${glyph}</span>
    <div class="ms-body"><b>${t(it.name, old)}</b>${meta.join("")}${it.details ? `<p>${t(it.details, old)}</p>` : ""}</div>
  </li>`;
}

export function renderDay(day, index, old = true) {
  const n = index + 1;
  const lod = day.lodging && day.lodging.name
    ? `<div class="ms-lodging"><span aria-hidden="true">☾</span> ${old ? "Ночлегъ" : "Ночёвка"}: <b>${t(day.lodging.name, old)}</b>${day.lodging.price_rub ? ` · ${Number(day.lodging.price_rub).toLocaleString("ru-RU")} ₽` : ""}</div>`
    : "";
  return `<section class="ms-day" data-day="${n}">
    <h3 class="ms-day-title"><span class="ms-glava">Глава</span><span class="ms-glava-num">${cyrillicNumeral(n, { html: true })}</span>${t(day.title || `День ${ORDINALS[index] || n}`, old)}</h3>
    <div class="ms-date">${old ? oldDate(day.date, { html: true }) : esc(day.date)}</div>
    ${weatherLine(day.weather, old)}
    <ol class="ms-items">${(day.items || []).map((it) => renderItem(it, old)).join("")}</ol>
    ${lod}
  </section>`;
}

export function renderChecks(checks = [], summary = {}, old = true) {
  if (!checks.length) return "";
  const rows = checks.map((c) => `<li class="ms-check ${c.ok ? "ok" : c.severity === "warn" ? "warn" : "bad"}">
      <span class="ms-check-mark" aria-label="${c.ok ? "сходится" : "противоречие"}">${c.ok ? "✓" : c.severity === "warn" ? "!" : "✗"}</span>${t(c.text, old)}</li>`).join("");
  const converges = summary.converges ?? checks.every((c) => c.ok || c.severity === "warn");
  const seal = `<div class="ms-seal ${converges ? "ok" : "bad"}" role="img" aria-label="${converges ? "План сходится" : "Есть противоречия"}">
      <span>${converges ? "Свѣрено" : "Есть<br>противорѣчія"}</span><small>${summary.passed ?? ""}/${summary.total ?? ""}</small></div>`;
  return `<section class="ms-checks"><h3>${old ? "Свѣрка съ міромъ" : "Сверка с реальностью"}</h3><div class="ms-checks-grid"><ul>${rows}</ul>${seal}</div></section>`;
}

export function renderMetrics(m = {}, model = "") {
  const parts = [];
  if (m.latency_s != null) parts.push(`${String(m.latency_s).replace(".", ",")} с`);
  if (m.total_tokens != null) parts.push(`${Number(m.total_tokens).toLocaleString("ru-RU")} токеновъ`);
  if (m.cost_usd) parts.push(`$${Number(m.cost_usd).toFixed(4)}`);
  if (m.llm_calls != null) parts.push(`шаговъ агента ${m.llm_calls}`);
  if (model) parts.push(esc(model));
  return parts.join(" · ");
}

export function renderManuscript(result, { old = true, now = new Date() } = {}) {
  const plan = result.plan || {};
  const zachin = String(plan.zachin || "Гой еси, добрый путникъ!");
  const zText = old ? toOldOrthography(zachin) : zachin;
  const first = [...zText][0] || "Г";
  const rest = zText.slice(first.length);
  const transport = TRANSPORT[plan.transport] || "";
  const cautions = (plan.cautions || []).map((c) => `<li>${t(c, old)}</li>`).join("");
  const sources = (result.sources || []).map(esc).join(" · ");
  return `<article class="scroll" aria-label="Грамота с планом поездки">
    <div class="scroll-rod" aria-hidden="true"></div>
    <div class="sheet">
      <div class="ms-ornament" aria-hidden="true"></div>
      <header class="ms-head">
        <h2 class="ms-title">${t(plan.title || "Путевая грамота", old)}</h2>
        ${transport ? `<div class="ms-transport">${esc(old ? transport : transport.replace(/ъ$/, ""))}</div>` : ""}
        ${plan.summary ? `<p class="ms-summary">${t(plan.summary, old)}</p>` : ""}
      </header>
      <p class="ms-zachin"><span class="bukvitsa" aria-hidden="true">${esc(first)}</span><span class="sr-only">${esc(first)}</span>${esc(rest)}</p>
      ${(plan.days || []).map((d, i) => renderDay(d, i, old)).join('<div class="ms-divider" aria-hidden="true">❦</div>')}
      ${cautions ? `<section class="ms-cautions"><h3>${old ? "Что вѣдать надобно" : "Что учесть"}</h3><ul>${cautions}</ul></section>` : ""}
      ${renderChecks(result.checks, result.check_summary, old)}
      <footer class="ms-colophon">
        <p>${old ? colophon(now, { html: true }) : `Составлено ${esc(now.toLocaleDateString("ru-RU"))}`}</p>
        <p class="ms-metrics">${renderMetrics(result.metrics, result.model)}</p>
        ${sources ? `<p class="ms-sources">Источники: ${sources}</p>` : ""}
      </footer>
    </div>
    <div class="scroll-rod" aria-hidden="true"></div>
  </article>`;
}

export function renderRefusal(result, { old = true } = {}) {
  const r = result.refusal || {};
  const titles = { off_topic: "Сіе не о странствіяхъ", other_region: "Земли сіи мнѣ невѣдомы", injection: "Устава не преступаю", too_long: "Челобитная длинна" };
  return `<article class="scroll scroll-small refusal" aria-label="Отказ">
    <div class="scroll-rod" aria-hidden="true"></div>
    <div class="sheet">
      <h2 class="ms-title">${esc(titles[r.category] || "Отказная грамота")}</h2>
      <p class="ms-zachin">${t(r.message || "", old)}</p>
      <p class="ms-metrics">${r.by === "prefilter" ? "Отклонено стражей у воротъ — безъ вызова LLM, 0 токеновъ" : renderMetrics(result.metrics, result.model)}</p>
    </div>
    <div class="scroll-rod" aria-hidden="true"></div>
  </article>`;
}

export function renderTraceLine(ev) {
  if (ev.type === "tool") return `<li class="tr-tool"><b>${esc(TOOL_LABELS[ev.name] || ev.name)}</b></li>`;
  if (ev.type === "tool_result") return `<li class="tr-result">${esc(ev.summary)}</li>`;
  if (ev.type === "thinking") return `<li class="tr-think">Шаг ${esc(ev.step)}: модель решает, что делать дальше</li>`;
  if (ev.type === "check") {
    const s = ev.summary || {};
    return `<li class="tr-check ${s.converges ? "ok" : "bad"}">${TOOL_LABELS.validate_plan}: ${s.passed} из ${s.total}${(ev.failed || []).length ? ". Не сходится: " + esc(ev.failed.join("; ")) : ""}</li>`;
  }
  if (ev.type === "guard") return `<li class="tr-check bad">${TOOL_LABELS.precheck}: ${esc(GUARD_TEXT[ev.category] || ev.category)}</li>`;
  return "";
}

// ---------- Современный вид ----------

const GUARD_TEXT = { off_topic: "запрос не о поездке", other_region: "это не Приморский край", injection: "попытка сменить правила", too_long: "слишком длинный запрос", empty: "пустой запрос" };
const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
const WEEKDAYS = ["воскресенье", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота"];
const TRANSPORT_RU = { car: "На машине", bike: "На велосипеде", foot: "Пешком", bus: "На автобусе", train: "На электричке" };
const KIND_RU = { transfer: "дорога", food: "еда", lodging: "ночёвка", note: "заметка" };
export const DAY_COLORS = ["#f0641e", "#2e6b62", "#2f5d8a", "#8a5a00", "#6b3fa0", "#00796b", "#9c2f6b"];

export function humanDate(iso) {
  const d = new Date(`${String(iso).slice(0, 10)}T12:00:00`);
  if (Number.isNaN(d.getTime())) return String(iso || "");
  const wd = WEEKDAYS[d.getDay()];
  return `${wd[0].toUpperCase()}${wd.slice(1)}, ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

export function weatherIcon(summary = "") {
  const s = summary.toLowerCase();
  if (/гроз/.test(s)) return "⛈";
  if (/снег/.test(s)) return "❄";
  if (/туман|изморозь/.test(s)) return "🌫";
  if (/дожд|ливн|морос/.test(s)) return "🌧";
  if (/пасмурн/.test(s)) return "☁";
  if (/облач/.test(s)) return "⛅";
  if (/ясн/.test(s)) return "☀";
  return "🌤";
}

function weatherChip(w) {
  if (!w) return "";
  const temp = w.tmin != null && w.tmax != null ? `${Math.round(w.tmin)}…${Math.round(w.tmax)}°` : "";
  const risks = w.risks || [];
  const parts = [temp, w.wind_max_ms != null ? `ветер ${Math.round(w.wind_max_ms)} м/с` : "", w.sunset ? `закат ${w.sunset}` : ""].filter(Boolean);
  return `<div class="day-weather${risks.length ? " risk" : ""}" title="${esc(w.summary || "")}"><span class="wx-icon" aria-hidden="true">${weatherIcon(w.summary)}</span>` +
    `<span>${esc(risks.length ? `${w.summary}: ${risks.join(", ")}` : w.summary || "")}${parts.length ? ", " + esc(parts.join(", ")) : ""}</span></div>`;
}

function stop(it) {
  const kind = KIND_RU[it.type];
  return `<li class="stop type-${esc(it.type || "note")}"><time>${esc(it.time || "")}</time><div>` +
    `<b>${esc(it.name)}</b>${kind ? `<span class="stop-kind">${kind}</span>` : ""}${it.details ? `<p>${esc(it.details)}</p>` : ""}</div></li>`;
}

export function renderVerify(checks = [], summary = {}) {
  if (!checks.length) return "";
  const ok = summary.converges ?? checks.every((c) => c.ok || c.severity === "warn");
  const failed = checks.filter((c) => !c.ok && c.severity !== "warn").length;
  const text = ok ? `План сходится: пройдено ${summary.passed ?? checks.filter((c) => c.ok).length} проверок из ${summary.total ?? checks.length}`
    : `Есть противоречия: ${failed} из ${summary.total ?? checks.length} проверок не прошли`;
  const rows = checks.map((c) => {
    const cls = c.ok ? "ok" : c.severity === "warn" ? "warn" : "bad";
    return `<li class="${cls}"><span class="chk ${cls}" aria-label="${c.ok ? "пройдено" : "не пройдено"}">${c.ok ? "✓" : cls === "warn" ? "!" : "✕"}</span><span>${esc(c.text)}</span></li>`;
  }).join("");
  return `<details class="verify ${ok ? "ok" : "bad"}"${ok ? "" : " open"}><summary><span class="verify-mark" aria-hidden="true">${ok ? "✓" : "!"}</span>` +
    `<span class="verify-text">${esc(text)}</span><span class="verify-more">Что проверили</span></summary><ul>${rows}</ul></details>`;
}

export function renderFoot(result) {
  const m = result.metrics || {};
  const parts = [];
  if (m.latency_s != null) parts.push(`Собран за ${String(m.latency_s).replace(".", ",")} с`);
  if (m.total_tokens) parts.push(`${Number(m.total_tokens).toLocaleString("ru-RU")} токенов`);
  if (m.cost_usd) parts.push(`$${Number(m.cost_usd).toFixed(4)}`);
  if (m.llm_calls) parts.push(`шагов агента: ${m.llm_calls}`);
  if (result.model) parts.push(`модель ${esc(result.model)}`);
  const src = (result.sources || []).length ? `<span>Источники: ${(result.sources || []).map(esc).join(", ")}</span>` : "";
  return `<footer class="plan-foot">${parts.map((p) => `<span>${p}</span>`).join("")}${src}</footer>`;
}

export function renderPlan(result) {
  const plan = result.plan || {};
  const days = plan.days || [];
  const facts = [];
  if (days.length) facts.push(["Даты", days.length > 1 ? `${humanDate(days[0].date)} — ${humanDate(days[days.length - 1].date)}` : humanDate(days[0].date)]);
  if (TRANSPORT_RU[plan.transport]) facts.push(["Как едем", TRANSPORT_RU[plan.transport]]);
  facts.push(["Дней", String(days.length)]);
  const nights = days.filter((d) => d.lodging && d.lodging.name).length;
  if (nights) facts.push(["Ночёвок", String(nights)]);
  const dayHtml = days.map((d, i) => {
    const lod = d.lodging && d.lodging.name
      ? `<div class="lodging"><span><span class="lodging-k">Ночёвка:</span> ${esc(d.lodging.name)}</span>${d.lodging.price_rub ? `<span>${Number(d.lodging.price_rub).toLocaleString("ru-RU")} ₽ за ночь</span>` : ""}</div>`
      : "";
    return `<li class="day"><span class="day-num" style="background:${DAY_COLORS[i % DAY_COLORS.length]}">${i + 1}</span>
      <div class="day-head"><div><h3>${esc(humanDate(d.date))}</h3>${d.title ? `<p class="day-sub">${esc(d.title)}</p>` : ""}</div>${weatherChip(d.weather)}</div>
      <ol class="stops">${(d.items || []).map(stop).join("")}</ol>${lod}</li>`;
  }).join("");
  const cautions = (plan.cautions || []).map((c) => `<li>${esc(c)}</li>`).join("");
  return `<article class="plan" aria-label="План поездки">
    <header class="plan-head"><h2>${esc(plan.title || "План поездки")}</h2>${plan.summary ? `<p>${esc(plan.summary)}</p>` : ""}
      <ul class="facts">${facts.map(([k, v]) => `<li><span class="fact-k">${esc(k)}</span><span class="fact-v">${esc(v)}</span></li>`).join("")}</ul></header>
    ${renderVerify(result.checks, result.check_summary)}
    <ol class="days">${dayHtml}</ol>
    ${cautions ? `<section class="cautions"><h3>Что учесть</h3><ul>${cautions}</ul></section>` : ""}
    ${renderFoot(result)}
  </article>`;
}

const NOTICE_TITLES = { off_topic: "Это не о поездке", other_region: "Это не Приморский край", injection: "Правила остаются прежними", too_long: "Слишком длинный запрос", empty: "Запрос пустой", unsafe: "С этим не помогу" };

export function renderNotice(result, mascotSvg = "") {
  if (result.status === "declined") {
    const r = result.refusal || {};
    const by = r.by === "prefilter" ? "Отклонено фильтром до вызова модели: 0 токенов." : "";
    return `<div class="notice refusal"><div class="notice-art sad">${mascotSvg}</div><div><h2>${esc(NOTICE_TITLES[r.category] || "Не могу помочь")}</h2>` +
      `<p>${esc(r.message || "")}</p>${by ? `<small>${by}</small>` : ""}</div></div>`;
  }
  const text = result.status === "text" ? result.text : result.error || "неизвестная ошибка";
  return `<div class="notice"><div class="notice-art sad">${mascotSvg}</div><div><h2>Не получилось собрать план</h2><p class="error-box">${esc(text)}</p></div></div>`;
}
