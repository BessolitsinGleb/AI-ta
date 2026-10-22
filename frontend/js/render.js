// Рендер ответа агента: современный план, «Бортовой журнал», вопросы, шаги агента. Чистые функции → HTML.

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

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
  find_food: "Ищу, где поесть",
  ask_user: "Уточняю детали у вас",
  submit_plan: "Собираю план",
  decline_request: "Отказываю: запрос не по теме",
  precheck: "Фильтр запросов",
  validate_plan: "Проверка плана",
};

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

export function linksHtml(links = []) {
  const safe = links.filter((l) => /^https:\/\//.test(String(l.url || "")));
  if (!safe.length) return "";
  return `<span class="links">${safe.map((l) => `<a href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">${esc(l.title)}</a>`).join("")}</span>`;
}

// Точка с координатами связана с картой: клик по ней показывает метку (см. app.js, drawMap)
const onMap = (it) => Number.isFinite(parseFloat(it?.lat)) && Number.isFinite(parseFloat(it?.lon));
const mapRef = (it, day, item) => (onMap(it) ? ` data-map-day="${day}" data-map-item="${item}" tabindex="0" title="Показать на карте"` : "");

function stop(it, day, i) {
  const kind = KIND_RU[it.type];
  return `<li class="stop type-${esc(it.type || "note")}"${mapRef(it, day, i)}><time>${esc(it.time || "")}</time><div>` +
    `<b>${esc(it.name)}</b>${kind ? `<span class="stop-kind">${kind}</span>` : ""}${it.details ? `<p>${esc(it.details)}</p>` : ""}` +
    `${linksHtml(it.links)}</div></li>`;
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
  if (m.estimated) parts.push("демо-режим без LLM: расход токенов не считается");
  else {
    if (m.total_tokens) parts.push(`${Number(m.total_tokens).toLocaleString("ru-RU")} токенов`);
    if (m.cost_usd) parts.push(`$${Number(m.cost_usd).toFixed(4)}`);
  }
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
      ? `<div class="lodging"${mapRef(d.lodging, i, "lodging")}><span><span class="lodging-k">Ночёвка:</span> ${esc(d.lodging.name)}${d.lodging.price_rub ? `, ~${Number(d.lodging.price_rub).toLocaleString("ru-RU")} ₽ за ночь` : ""}</span>${linksHtml(d.lodging.links)}</div>`
      : "";
    return `<li class="day"><span class="day-num" data-focus-day="${i}" role="button" tabindex="0" title="Показать этот день на карте" style="background:${DAY_COLORS[i % DAY_COLORS.length]}">${i + 1}</span>
      <div class="day-head"><div><h3>${esc(humanDate(d.date))}</h3>${d.title ? `<p class="day-sub">${esc(d.title)}</p>` : ""}</div>${weatherChip(d.weather)}</div>
      <ol class="stops">${(d.items || []).map((it, k) => stop(it, i, k)).join("")}</ol>${lod}</li>`;
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

// ---------- Вопросы ----------

export function renderQuestions(result, mascotSvg = "") {
  const qs = result.questions || [];
  const blocks = qs.map((q, i) => `<fieldset class="q" data-q="${i}"><legend>${esc(q.text)}</legend>
      <div class="q-opts">${q.options.map((o) => `<button type="button" class="chip q-opt" aria-pressed="false" data-value="${esc(o)}">${esc(o)}</button>`).join("")}</div></fieldset>`).join("");
  return `<form class="questions" id="questions"><div class="questions-head"><div class="notice-art">${mascotSvg}</div>
      <div><h2>Пара уточнений</h2><p>Ответьте, чтобы план получился точнее. Можно пропустить.</p></div></div>
      ${blocks}<div class="q-actions"><button type="submit" class="go">Собрать план</button><button type="button" class="ghost-btn" id="q-skip">Пропустить</button></div></form>`;
}

// ---------- «Бортовой журнал»: тот же план в морском стиле ----------

function coords(lat, lon) {
  if (lat == null || lon == null) return "";
  return `${Number(lat).toFixed(3)}, ${Number(lon).toFixed(3)}`;
}

const COMPASS = `<svg class="lb-compass" viewBox="0 0 100 100" aria-hidden="true"><circle cx="50" cy="50" r="46" fill="none" stroke="currentColor" stroke-width="1.5"/>
  <circle cx="50" cy="50" r="38" fill="none" stroke="currentColor" stroke-width=".7" stroke-dasharray="2 3"/>
  <path d="M50 6 L57 50 L50 94 L43 50 Z" fill="currentColor" opacity=".85"/><path d="M6 50 L50 43 L94 50 L50 57 Z" fill="currentColor" opacity=".35"/>
  <path d="M50 6 L57 50 L50 50 Z" fill="#d7392b"/><text x="50" y="4" font-size="9" text-anchor="middle" fill="currentColor" dy="-1">С</text></svg>`;

export function renderLogbook(result) {
  const plan = result.plan || {};
  const days = plan.days || [];
  const summ = result.check_summary || {};
  const rows = days.map((d, i) => {
    const w = d.weather;
    const wx = w ? `${weatherIcon(w.summary)} ${esc(w.summary || "")}${w.tmin != null ? `, ${Math.round(w.tmin)}…${Math.round(w.tmax)}°` : ""}${w.wind_max_ms != null ? `, ветер ${Math.round(w.wind_max_ms)} м/с` : ""}` : "";
    const items = (d.items || []).map((it) => `<tr class="lb-${esc(it.type || "note")}"><td class="lb-time">${esc(it.time || "")}</td>
        <td><b>${esc(it.name)}</b>${it.details ? `<div class="lb-note">${esc(it.details)}</div>` : ""}${linksHtml(it.links)}</td>
        <td class="lb-coord">${esc(coords(it.lat, it.lon))}</td></tr>`).join("");
    const lod = d.lodging?.name ? `<tr class="lb-lodging"><td class="lb-time">ночь</td><td><b>${esc(d.lodging.name)}</b>${linksHtml(d.lodging.links)}</td><td class="lb-coord">${esc(coords(d.lodging.lat, d.lodging.lon))}</td></tr>` : "";
    return `<section class="lb-day"><header><span class="lb-flag" style="background:${DAY_COLORS[i % DAY_COLORS.length]}">${i + 1}</span>
        <h3>${esc(humanDate(d.date))}</h3>${wx ? `<span class="lb-wx">${wx}</span>` : ""}</header>
        <table><thead><tr><th>Время</th><th>Пункт</th><th>Координаты</th></tr></thead><tbody>${items}${lod}</tbody></table></section>`;
  }).join("");
  const cautions = (plan.cautions || []).map((c) => `<li>${esc(c)}</li>`).join("");
  return `<article class="logbook" aria-label="Бортовой журнал поездки">
    <header class="lb-head">${COMPASS}<div><p class="lb-kicker">Бортовой журнал</p><h2>${esc(plan.title || "Поездка по Приморью")}</h2>
      ${plan.summary ? `<p class="lb-sum">${esc(plan.summary)}</p>` : ""}</div></header>
    ${rows}
    ${cautions ? `<section class="lb-cautions"><h3>Перед выходом</h3><ul>${cautions}</ul></section>` : ""}
    <footer class="lb-foot"><div class="lb-stamp ${summ.converges ? "ok" : "bad"}"><span>${summ.converges ? "Маршрут проверен" : "Есть замечания"}</span><small>${summ.passed ?? ""} из ${summ.total ?? ""}</small></div>
      ${renderFoot(result).replace('class="plan-foot"', 'class="plan-foot lb-meta"')}</footer>
  </article>`;
}
