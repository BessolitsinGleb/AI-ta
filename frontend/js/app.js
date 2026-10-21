import { esc, renderLogbook, renderNotice, renderPlan, renderQuestions, renderTraceLine } from "./render.js";

const $ = (sel) => document.querySelector(sel);
const state = { result: null, map: null, layers: null, mascot: "", busy: false, view: readView(), query: "" };

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

async function loadMeta() {
  try {
    const [vers, examples] = await Promise.all([
      fetch("/api/versions").then((r) => r.json()),
      fetch("/api/examples").then((r) => r.json()),
    ]);
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

function showResult(result) {
  state.result = result;
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

async function ask(query, answers) {
  if (state.busy) return;
  state.query = query;
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
    const resp = await fetch("/api/plan/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, version: $("#version").value || undefined, answers }),
    });
    if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let got = false;
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
        else if (ev.type === "result") { got = true; showResult(ev.result); }
        else addTrace(ev);
      }
    }
    if (!got) throw new Error("соединение оборвалось до результата");
  } catch (e) {
    showResult({ status: "error", error: e.message });
  } finally {
    state.busy = false;
    $("#submit").disabled = false;
    $("#ask").classList.remove("busy");
  }
}

loadMascot();
loadMeta();
setupForm();
