import { api, currentUser, freshAuthHeader, logout, onAuth, refresh } from "./api.js";
import * as pages from "./pages.js";
import { esc, humanDate, renderLogbook, renderNotice, renderPlan, renderQuestions, renderTraceLine, TOOL_LABELS } from "./render.js";

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

function drawMap(mp) {
  ensureMap();
  if (!state.map) return;
  state.layers.clearLayers();
  const bounds = [];
  const legend = [];
  (mp?.days || []).forEach((day) => {
    if (day.geometry?.length > 1) {
      L.polyline(day.geometry, { color: day.color, weight: 5, opacity: .9, dashArray: day.approx ? "3 9" : (mp.mode === "bus" || mp.mode === "train" ? "10 8" : null) })
        .bindTooltip(day.approx ? "Маршрут примерный: сервис дорог не ответил" : `День ${day.day}`).addTo(state.layers);
      bounds.push(...day.geometry);
    }
    day.markers.forEach((m, i) => {
      const icon = L.divIcon({ className: "", html: `<div class="pin" style="background:${day.color}"><span>${m.type === "lodging" ? "☾" : i + 1}</span></div>`, iconSize: [28, 28], iconAnchor: [14, 28] });
      L.marker([m.lat, m.lon], { icon, title: m.name }).bindPopup(`<b>${esc(m.name)}</b>${m.time ? `<br>${esc(m.time)}` : ""}`).addTo(state.layers);
      bounds.push([m.lat, m.lon]);
    });
    legend.push(`<span><i style="background:${day.color}"></i>День ${day.day}</span>`);
  });
  (mp?.fuel || []).forEach((s) => {
    const has = Object.values(s.fuel || {}).some(Boolean);
    L.circleMarker([s.lat, s.lon], { radius: 5, color: has ? "#2e6b62" : "#c2321f", fillOpacity: .9, weight: 2 })
      .bindPopup(`<b>${esc(s.name)}</b><br>${Object.entries(s.fuel || {}).map(([k, v]) => `${esc(k)}: ${v ? "есть" : "нет"}`).join(", ")}`)
      .addTo(state.layers);
  });
  if ((mp?.fuel || []).length) legend.push(`<span><i style="background:#2e6b62;height:8px;width:8px;border-radius:50%"></i>АЗС с топливом</span>`);
  if ((mp?.days || []).some((d) => d.approx)) legend.push("<span>Пунктир — маршрут примерный</span>");
  $("#legend").innerHTML = legend.join("");
  if (bounds.length) state.map.fitBounds(bounds, { padding: [24, 24], maxZoom: 13 });
  setTimeout(() => state.map.invalidateSize(), 50);
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
onAuth(renderAccount);
window.addEventListener("hashchange", route);
// восстанавливаем сессию по refresh-cookie и загружаем маскота, потом показываем страницу
Promise.all([refresh(), mascotReady]).finally(route);
