import { api, currentUser, freshAuthHeader, logout, onAuth, refresh } from "./api.js";
import * as pages from "./pages.js";
import { esc, humanDate, linksHtml, renderLogbook, renderNotice, renderPlan, renderQuestions, renderTraceLine, TOOL_LABELS } from "./render.js";

const $ = (sel) => document.querySelector(sel);
const state = { result: null, map: null, layers: null, mascot: "", busy: false, view: readView(), query: "", conversation: null, loginRequired: true };
const PENDING_KEY = "amba-pending-query";

function readView() {
  try { return localStorage.getItem("amba-view") === "logbook" ? "logbook" : "modern"; } catch { return "modern"; }
}

function setView(view) {
  state.view = view;
  try { localStorage.setItem("amba-view", view); } catch { /* приватный режим */ }
  document.querySelectorAll(".seg-btn").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.view === view)));
  if (state.result) showResult(state.result);
}

async function loadMascot() {
  try {
    state.mascot = await (await fetch("/static/assets/amba.svg")).text();
  } catch {
    state.mascot = "";
  }
  document.querySelectorAll("[data-mascot]").forEach((el) => { el.innerHTML = state.mascot; });
}

// ---------- уведомления ----------

let toastTimer;
function toast(html) {
  const t = $("#toast");
  t.innerHTML = html;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 6000);
}

// ---------- аккаунт в шапке ----------

// Гостю поиск закрыт: подсказка под формой и кнопка «Войти и собрать план»
function renderGuestNote() {
  const guest = !currentUser() && state.loginRequired;
  $("#guest-note").hidden = !guest;
  $("#submit").textContent = guest ? "Войти и собрать план" : "Собрать план";
}

// Запрос гостя ждёт входа: после логина план соберётся сам (полчаса — чтобы не всплыл через день)
function askLogin(query) {
  try { localStorage.setItem(PENDING_KEY, JSON.stringify({ query, at: Date.now() })); } catch { /* приватный режим */ }
  toast("Войдите, чтобы Амба собрала план. Запрос сохранили — продолжим сразу после входа");
  navigate("/login?next=/");
}

function takePending() {
  try {
    const raw = localStorage.getItem(PENDING_KEY);
    localStorage.removeItem(PENDING_KEY);
    const p = raw && JSON.parse(raw);
    return p && Date.now() - p.at < 30 * 60 * 1000 ? p.query : "";
  } catch { return ""; }
}

function renderAccount(user) {
  renderGuestNote();
  const box = $("#account");
  if (!user) {
    box.innerHTML = '<a class="go small" href="#/login">Войти</a>';
  } else {
    const initials = (user.name || user.email).trim().slice(0, 1).toUpperCase();
    box.innerHTML = `<details class="acc-menu"><summary aria-label="Меню аккаунта"><span class="avatar">${esc(initials)}</span><span class="acc-name">${esc(user.name || user.email)}</span></summary>
      <div class="acc-drop"><a href="#/profile">Профиль</a><a href="#/onboarding">Мои интересы</a><a href="#/trips">Мои поездки</a>
      <button type="button" id="logout">Выйти</button></div></details>`;
    box.querySelector("#logout").addEventListener("click", async () => { await logout(); navigate("/"); });
  }
  loadForYou(user);
}

async function loadForYou(user) {
  const box = $("#for-you");
  if (!user?.onboarded) { box.hidden = true; return; }
  try {
    const r = await api("/api/recommendations");
    box.innerHTML = `<span class="examples-title">Для вас:</span>` + r.trips.slice(0, 3)
      .map((t) => `<button type="button" class="idea-chip" data-q="${esc(t.query)}"><span aria-hidden="true">${esc(t.emoji)}</span> ${esc(t.title)}</button>`).join("") +
      '<a class="more-link" href="#/recommendations">Все идеи</a>';
    box.hidden = false;
    box.querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => startPlan(b.dataset.q)));
  } catch { box.hidden = true; }
}

// ---------- роутер ----------

const ROUTES = {
  "/login": [pages.loginPage, false], "/register": [pages.registerPage, false], "/check-email": [pages.checkEmailPage, false],
  "/forgot": [pages.forgotPage, false], "/reset": [pages.resetPage, false],
  "/welcome": [(el, ctx) => pages.onboardingPage(el, { ...ctx, welcome: true }), true], "/onboarding": [pages.onboardingPage, true],
  "/profile": [pages.profilePage, true], "/trips": [pages.tripsPage, true], "/recommendations": [pages.recommendationsPage, true],
};

function navigate(path) {
  if (location.hash === `#${path}`) route();
  else location.hash = path;
}

function startPlan(query) {
  navigate("/");
  $("#q").value = query;
  ask(query);
}

async function route() {
  const raw = location.hash.slice(1) || "/";
  const [path, qs] = raw.split("?");
  const params = new URLSearchParams(qs || "");
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === (path.startsWith("/trips") ? "/trips" : path)));
  document.querySelector(".acc-menu")?.removeAttribute("open");
  const page = $("#page");
  const trip = path.match(/^\/trips\/([a-f0-9]{32})$/);
  if (path === "/" || trip) {
    page.hidden = true;
    $("#planner").hidden = false;
    $("#saved-banner").hidden = true;
    if (trip) {
      if (!currentUser()) return navigate(`/login?next=${encodeURIComponent(path)}`);
      openTrip(trip[1]);
    } else if (currentUser()) {
      const pending = takePending();
      if (pending) startPlan(pending);
    }
    return;
  }
  const [render, needsAuth] = ROUTES[path] || [];
  if (!render) return navigate("/");
  if (needsAuth && !currentUser()) return navigate(`/login?next=${encodeURIComponent(path)}`);
  $("#planner").hidden = true;
  page.hidden = false;
  window.scrollTo(0, 0);
  try {
    await render(page, { params, navigate, startPlan, mascot: state.mascot });
  } catch (e) {
    page.innerHTML = `<div class="acc-card narrow"><h1>Не получилось загрузить</h1><p class="error-box">${esc(e.message)}</p></div>`;
  }
}

async function openTrip(id) {
  try {
    const t = await api(`/api/trips/${id}`);
    const banner = $("#saved-banner");
    banner.innerHTML = `<div><b>Сохранённая поездка</b> от ${esc(humanDate(t.created_at))}: «${esc(t.query)}»</div>
      <div class="q-actions"><button type="button" class="ghost-btn" id="replan">Собрать заново</button><a class="ghost-btn" href="#/trips">Все поездки</a></div>`;
    banner.hidden = false;
    banner.querySelector("#replan").addEventListener("click", () => startPlan(t.query));
    $("#workspace").hidden = false;
    showIntents(t.result.intents);
    $("#trace").innerHTML = (t.result.trace || []).filter((x) => x.kind === "tool")
      .map((x) => `<li class="tr-tool"><b>${esc(TOOL_LABELS[x.name] || x.name)}</b></li>${x.summary ? `<li class="tr-result">${esc(x.summary)}</li>` : ""}`).join("");
    ensureMap();
    renderChat(null);  // у сохранённой поездки диалога нет — для правок «Собрать заново»
    showResult(t.result);
    banner.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    toast(esc(e.message));
    navigate("/trips");
  }
}

async function loadMeta() {
  try {
    const [vers, examples] = await Promise.all([
      fetch("/api/versions").then((r) => r.json()),
      fetch("/api/examples").then((r) => r.json()),
    ]);
    state.loginRequired = vers.login_required !== false;
    renderGuestNote();
    const sel = $("#version");
    sel.innerHTML = vers.versions.map((v) =>
      `<option value="${esc(v.key)}"${v.key === vers.default ? " selected" : ""}>${esc(v.key)} · ${esc(v.label)}${vers.demo ? "" : ` — ${esc(v.model)}`}</option>`).join("");
    if (vers.demo) {
      const badge = $("#mode-badge");
      badge.hidden = false;
      badge.textContent = "Демо-режим без LLM";
      badge.title = "Добавьте OPENROUTER_API_KEY в .env, чтобы планы строила модель";
    }
    $("#examples").innerHTML = examples.map((q) => `<button type="button" class="example">${esc(q)}</button>`).join("");
  } catch (e) {
    console.warn("meta", e);
  }
}

function setupForm() {
  const chips = [...document.querySelectorAll("#transport .chip")];
  chips.forEach((chip) => chip.addEventListener("click", () => {
    const on = chip.getAttribute("aria-pressed") !== "true";
    chips.forEach((c) => c.setAttribute("aria-pressed", "false"));
    chip.setAttribute("aria-pressed", String(on));
  }));
  $("#examples").addEventListener("click", (e) => {
    const btn = e.target.closest(".example");
    if (!btn) return;
    $("#q").value = btn.textContent;
    chips.forEach((c) => c.setAttribute("aria-pressed", "false"));
    $("#q").focus();
  });
  $("#q").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("#ask").requestSubmit();
  });
  $("#ask").addEventListener("submit", (e) => {
    e.preventDefault();
    let q = $("#q").value.trim();
    const mode = chips.find((c) => c.getAttribute("aria-pressed") === "true")?.dataset.mode;
    if (mode && !q.toLowerCase().includes(mode.split(" ").pop().slice(0, 5))) q = `${q}, ${mode}`;
    if (q) ask(q);
  });
  document.querySelectorAll(".seg-btn").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
  setView(state.view);
  $("#print").addEventListener("click", () => window.print());
  $("#chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("#chat-input");
    const msg = input.value.trim();
    input.value = "";
    refine(msg);
  });
  $("#chat-chips").addEventListener("click", (e) => {
    const b = e.target.closest("[data-say]");
    if (b) refine(b.dataset.say);
  });
}

function mascotHtml(cls) {
  return `<div class="loading-art ${cls}">${state.mascot}</div>`;
}

function setLoading() {
  const text = "Амба собирает план…";
  $("#result").innerHTML = `<div class="loading">${mascotHtml("writing")}<p>${text}</p></div>`;
}

function showIntents(intents) {
  const box = $("#intents");
  const chips = intents?.chips || [];
  box.innerHTML = chips.map((c) => `<span class="intent" title="Понял из запроса">${esc(c)}</span>`).join("");
}

function addTrace(ev) {
  const html = renderTraceLine(ev);
  if (!html) return;
  const list = $("#trace");
  list.insertAdjacentHTML("beforeend", html);
  list.scrollTop = list.scrollHeight;
}

function ensureMap() {
  if (state.map || typeof L === "undefined") return;
  state.map = L.map("map", { zoomControl: true, attributionControl: true }).setView([43.4, 132.6], 7);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(state.map);
  state.layers = L.layerGroup().addTo(state.map);
}

// ---------- карта: дни — отдельные слои, легенда — переключатели, план и карта связаны ----------

const WIDE = window.matchMedia("(min-width: 1101px)");  // на широком экране карта висит сбоку от плана
const sameSpot = (m, it) => it && it.name === m.name && Math.abs(Number(it.lat) - m.lat) < 1e-6 && Math.abs(Number(it.lon) - m.lon) < 1e-6;

function popupHtml(m, item, dayNum) {
  const meta = [`День ${dayNum}`, m.time, m.type === "lodging" ? "ночёвка" : ""].filter(Boolean).join(" · ");
  return `<b>${esc(m.name)}</b><br><span class="pop-meta">${esc(meta)}</span>${linksHtml(item?.links)}`;
}

function drawMap(mp) {
  ensureMap();
  if (!state.map) return;
  state.layers.clearLayers();
  const planDays = state.result?.plan?.days || [];
  state.mapDays = (mp?.days || []).map((day, d) => {
    const group = L.featureGroup();
    if (day.geometry?.length > 1) {
      L.polyline(day.geometry, { color: day.color, weight: 5, opacity: .9, dashArray: day.approx ? "3 9" : (mp.mode === "bus" || mp.mode === "train" ? "10 8" : null) })
        .bindTooltip(day.approx ? `День ${day.day}: маршрут примерный, сервис дорог не ответил` : `День ${day.day}`, { sticky: true })
        .on("click", () => focusDay(state.focusDay === d ? null : d))
        .addTo(group);
    }
    const items = planDays[d]?.items || [];
    const markers = day.markers.map((m, i) => {
      const lodging = m.type === "lodging";
      const item = lodging ? planDays[d]?.lodging : items.find((it) => sameSpot(m, it));
      const icon = L.divIcon({ className: "", html: `<div class="pin" style="background:${day.color}"><span>${lodging ? "☾" : i + 1}</span></div>`,
        iconSize: [28, 28], iconAnchor: [14, 28], popupAnchor: [0, -26] });
      const ref = { lodging, item: lodging ? "lodging" : String(items.indexOf(item)) };
      ref.marker = L.marker([m.lat, m.lon], { icon, title: m.name, riseOnHover: true }).bindPopup(popupHtml(m, item, day.day))
        .on("click", () => flashStop(d, ref)).addTo(group);
      return ref;
    });
    group.addTo(state.layers);
    return { group, markers };
  });
  state.fuelLayer = L.layerGroup((mp?.fuel || []).map((s) => {
    const has = Object.values(s.fuel || {}).some(Boolean);
    return L.circleMarker([s.lat, s.lon], { radius: 5, color: has ? "#2e6b62" : "#c2321f", fillOpacity: .9, weight: 2 })
      .bindPopup(`<b>${esc(s.name)}</b><br>${Object.entries(s.fuel || {}).map(([k, v]) => `${esc(k)}: ${v ? "есть" : "нет"}`).join(", ")}`);
  })).addTo(state.layers);
  state.focusDay = null;
  renderLegend(mp);
  fitMap(false);
  setTimeout(() => state.map.invalidateSize(), 50);
}

function renderLegend(mp) {
  const days = mp?.days || [];
  const parts = days.length > 1 ? ['<button type="button" class="lg-btn" data-day="all" aria-pressed="true">Все дни</button>'] : [];
  days.forEach((day, i) => parts.push(`<button type="button" class="lg-btn" data-day="${i}" aria-pressed="false" style="--c:${day.color}" title="Показать только этот день"><i></i>День ${day.day}</button>`));
  if ((mp?.fuel || []).length) parts.push('<button type="button" class="lg-btn" data-fuel aria-pressed="true" title="Показать или скрыть заправки"><i class="dot"></i>АЗС с топливом</button>');
  if (days.some((d) => d.approx)) parts.push('<span class="lg-note">Пунктир — маршрут примерный</span>');
  $("#legend").innerHTML = parts.join("");
}

// Оставить на карте один день (d) или все (null); подсветить его в плане
function focusDay(d) {
  if (!state.mapDays?.length) return;
  state.focusDay = d;
  state.mapDays.forEach((day, i) => {
    if (d === null || i === d) day.group.addTo(state.layers);
    else state.layers.removeLayer(day.group);
  });
  const key = d === null ? "all" : String(d);
  document.querySelectorAll("#legend [data-day]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.day === key)));
  document.querySelectorAll("#result .day").forEach((el, i) => el.classList.toggle("map-focus", i === d));
  fitMap(true);
}

function fitMap(animate) {
  const bounds = L.latLngBounds([]);
  state.mapDays.forEach((day, i) => {
    if (state.focusDay !== null && i !== state.focusDay) return;
    const b = day.group.getBounds();
    if (b.isValid()) bounds.extend(b);
  });
  if (bounds.isValid()) state.map.fitBounds(bounds, { padding: [24, 24], maxZoom: state.focusDay === null ? 13 : 15, animate });
}

function mapRef(el) {
  const day = state.mapDays?.[Number(el.dataset.mapDay)];
  return day?.markers.find((r) => r.item === el.dataset.mapItem);
}

// Точка из плана → метка на карте
function showOnMap(el) {
  const ref = mapRef(el);
  if (!ref) return;
  const d = Number(el.dataset.mapDay);
  if (state.focusDay !== null && state.focusDay !== d) focusDay(d);
  state.map.flyTo(ref.marker.getLatLng(), Math.max(state.map.getZoom(), 15), { duration: .6 });
  ref.marker.openPopup();
  if (!WIDE.matches) $("#map").scrollIntoView({ behavior: "smooth", block: "center" });
}

// Метка на карте → точка в плане
function flashStop(d, ref) {
  const el = document.querySelector(`#result [data-map-day="${d}"][data-map-item="${ref.item}"]`);
  if (!el) return;
  el.classList.remove("flash");
  void el.offsetWidth;  // перезапуск анимации при повторном клике
  el.classList.add("flash");
  const r = el.getBoundingClientRect();
  if (WIDE.matches && (r.top < 0 || r.bottom > window.innerHeight)) el.scrollIntoView({ behavior: "smooth", block: "center" });
}

let hotRef = null;
function setHot(ref) {
  if (hotRef === ref) return;
  if (hotRef) { hotRef.marker.getElement()?.classList.remove("pin-hot"); hotRef.marker.setZIndexOffset(0); }
  hotRef = ref || null;
  if (hotRef) { hotRef.marker.getElement()?.classList.add("pin-hot"); hotRef.marker.setZIndexOffset(1000); }
}

function setupMapLinks() {
  $("#legend").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if ("fuel" in b.dataset) {
      const on = b.getAttribute("aria-pressed") !== "true";
      b.setAttribute("aria-pressed", String(on));
      if (on) state.fuelLayer.addTo(state.layers); else state.layers.removeLayer(state.fuelLayer);
      return;
    }
    const d = b.dataset.day === "all" ? null : Number(b.dataset.day);
    focusDay(d === state.focusDay ? null : d);
  });
  const act = (e) => {
    if (e.target.closest("a, button")) return false;
    const dayEl = e.target.closest("[data-focus-day]");
    if (dayEl) {
      const d = Number(dayEl.dataset.focusDay);
      focusDay(state.focusDay === d ? null : d);
      if (!WIDE.matches) $("#map").scrollIntoView({ behavior: "smooth", block: "center" });
      return true;
    }
    const stopEl = e.target.closest("[data-map-day]");
    if (stopEl) { showOnMap(stopEl); return true; }
    return false;
  };
  const result = $("#result");
  result.addEventListener("click", act);
  result.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && act(e)) e.preventDefault();
  });
  result.addEventListener("mouseover", (e) => {
    const el = e.target.closest("[data-map-day]");
    setHot(el ? mapRef(el) : null);
  });
  result.addEventListener("mouseleave", () => setHot(null));
}

function renderChat(conv) {
  const chat = $("#chat");
  state.conversation = conv || null;
  if (!conv) { chat.hidden = true; return; }
  chat.hidden = false;
  $("#chat-log").innerHTML = conv.turns.slice(2).map((t) => `<li class="msg ${t.role}">${esc(t.text)}</li>`).join("");
  const can = conv.can_refine !== false;
  $("#chat-form").hidden = !can;
  $("#chat-chips").hidden = !can;
  $("#chat-note").textContent = can ? "История диалога хранится сутки." : "Правок уже много — соберите новый план с учётом пожеланий.";
}

function showResult(result) {
  state.result = result;
  if ("conversation" in result || result.status !== "plan") renderChat(result.conversation);
  const out = $("#result");
  $("#print").disabled = result.status !== "plan";
  if (result.status === "plan") {
    out.innerHTML = state.view === "logbook" ? renderLogbook(result) : renderPlan(result);
    drawMap(result.map);
  } else if (result.status === "question") {
    out.innerHTML = renderQuestions(result, state.mascot);
    bindQuestions(result);
    drawMap(null);
  } else {
    out.innerHTML = renderNotice(result, state.mascot);
    drawMap(null);
  }
}

function bindQuestions(result) {
  const form = $("#questions");
  form.querySelectorAll(".q").forEach((fs) => fs.addEventListener("click", (e) => {
    const btn = e.target.closest(".q-opt");
    if (!btn) return;
    fs.querySelectorAll(".q-opt").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
  }));
  const collect = () => result.questions.map((q, i) => ({
    question: q.text,
    answer: form.querySelector(`.q[data-q="${i}"] .q-opt[aria-pressed="true"]`)?.dataset.value || "",
  }));
  form.addEventListener("submit", (e) => { e.preventDefault(); ask(state.query, collect()); });
  $("#q-skip").addEventListener("click", () => ask(state.query, []));
}

// Стрим плана: события агента → в «летопись», финальный результат возвращается. Ошибки HTTP — с текстом сервера.
async function streamPlan(body) {
  const resp = await fetch("/api/plan/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await freshAuthHeader()) },
    body: JSON.stringify({ version: $("#version").value || undefined, ...body }),
  });
  if (!resp.ok || !resp.body) {
    const data = await resp.json().catch(() => null);
    const err = new Error(typeof data?.detail === "string" ? data.detail : `Ошибка ${resp.status}`);
    err.status = resp.status;
    throw err;
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      const ev = JSON.parse(line.slice(6));
      if (ev.type === "start") showIntents(ev.intents);
      else if (ev.type === "result") return ev.result;
      else addTrace(ev);
    }
  }
  throw new Error("соединение оборвалось до результата");
}

async function refine(message) {
  if (state.busy || !state.conversation || !message.trim()) return;
  state.busy = true;
  const log = $("#chat-log");
  log.insertAdjacentHTML("beforeend", `<li class="msg user">${esc(message)}</li><li class="msg assistant pending">Амба дорабатывает план…</li>`);
  $("#chat-form").querySelector("button").disabled = true;
  $("#result").classList.add("refining");
  $("#trace").innerHTML = "";
  $("#trace-panel").open = true;
  try {
    const result = await streamPlan({ query: message, conversation_id: state.conversation.id });
    if (result.status === "plan") {
      showResult(result);
      afterResult(result);
    } else {
      renderChat(result.conversation || state.conversation);  // отказ или ошибка — прежний план остаётся на экране
      if (!result.conversation) log.insertAdjacentHTML("beforeend", `<li class="msg assistant err">${esc(result.error || "Не получилось")}</li>`);
    }
  } catch (e) {
    log.querySelector(".pending")?.remove();
    log.insertAdjacentHTML("beforeend", `<li class="msg assistant err">${esc(e.message)}</li>`);
  } finally {
    state.busy = false;
    $("#result").classList.remove("refining");
    $("#chat-form").querySelector("button").disabled = false;
  }
}

async function ask(query, answers) {
  if (state.busy) return;
  await metaReady;
  if (!currentUser() && state.loginRequired) return askLogin(query);
  state.query = query;
  renderChat(null);
  state.busy = true;
  $("#submit").disabled = true;
  $("#ask").classList.add("busy");
  $("#trace-panel").open = true;
  $("#workspace").hidden = false;
  $("#trace").innerHTML = "";
  showIntents(null);
  setLoading();
  ensureMap();
  setTimeout(() => state.map?.invalidateSize(), 50);
  $("#workspace").scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const result = await streamPlan({ query, answers });
    showResult(result);
    afterResult(result);
  } catch (e) {
    if (e.status === 401) {  // сессия истекла — после входа продолжим с того же запроса
      $("#workspace").hidden = true;
      askLogin(query);
    } else {
      showResult({ status: "error", error: e.message });
    }
  } finally {
    state.busy = false;
    $("#submit").disabled = false;
    $("#ask").classList.remove("busy");
  }
}

function afterResult(result) {
  if (result.trip_id && state.conversation && state.conversation.turns.length > 2) {
    toast(`План обновлён в <a href="#/trips/${esc(result.trip_id)}">«Мои поездки»</a>`);
  } else if (result.trip_id) {
    toast(`Сохранено в <a href="#/trips/${esc(result.trip_id)}">«Мои поездки»</a>`);
  } else if (result.status === "plan" && !currentUser() && !sessionStorage.getItem("amba-guest-hint")) {
    sessionStorage.setItem("amba-guest-hint", "1");
    toast('<a href="#/register">Зарегистрируйтесь</a>, чтобы поездки сохранялись, а Амба подбирал идеи под вас');
  }
}

const mascotReady = loadMascot();
const metaReady = loadMeta();
setupForm();
setupMapLinks();
onAuth(renderAccount);
window.addEventListener("hashchange", route);
// восстанавливаем сессию по refresh-cookie и загружаем маскота, потом показываем страницу
Promise.all([refresh(), mascotReady]).finally(route);
