// Рендер ответа агента в виде старорусской грамоты. Чистые функции → HTML-строки (тестируются в Node).
import { colophon, cyrillicNumeral, oldDate, ORDINALS, toOldOrthography } from "./oldstyle.js";

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

const t = (text, old) => esc(old ? toOldOrthography(text) : text);

export const TOOL_LABELS = {
  search_places: "Листаю книгу мѣстъ",
  get_weather: "Вопрошаю небо · Open-Meteo",
  build_route: "Мѣряю путь-дорогу · OSRM",
  find_fuel_stations: "Ищу, гдѣ коня напоить · АЗС",
  find_lodging: "Ищу ночлегъ",
  public_transport: "Справляюсь о повозкахъ · расписаніе",
  find_events: "Вызнаю о празднествахъ",
  geocode: "Ищу на картѣ · Nominatim",
  place_info: "Читаю лѣтопись · Википедія",
  submit_plan: "Переписываю грамоту набѣло",
  decline_request: "Пишу отказную грамоту",
  precheck: "Стража у воротъ",
  validate_plan: "Свѣряю съ міромъ",
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
  if (ev.type === "tool") return `<li class="tr-tool"><b>${esc(TOOL_LABELS[ev.name] || ev.name)}</b><code>${esc(ev.name)}</code></li>`;
  if (ev.type === "tool_result") return `<li class="tr-result">↳ ${esc(ev.summary)}</li>`;
  if (ev.type === "thinking") return `<li class="tr-think">Шагъ ${cyrillicNumeral(ev.step, { html: true })} · размышляю…</li>`;
  if (ev.type === "check") {
    const s = ev.summary || {};
    return `<li class="tr-check ${s.converges ? "ok" : "bad"}">${TOOL_LABELS.validate_plan}: ${s.passed}/${s.total}${(ev.failed || []).length ? " — " + esc(ev.failed.join("; ")) : ""}</li>`;
  }
  if (ev.type === "guard") return `<li class="tr-check bad">${TOOL_LABELS.precheck}: ${esc(ev.category)}</li>`;
  return "";
}
