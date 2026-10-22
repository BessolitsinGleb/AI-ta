// Страницы аккаунта: вход, регистрация, письмо, сброс пароля, анкета, профиль, поездки, рекомендации.
import { api, currentUser, login, logout, setSession, updateUser, validPassword } from "./api.js";
import { esc, humanDate } from "./render.js";

const TRANSPORT_RU = { car: "на машине", bike: "на велосипеде", foot: "пешком", bus: "на автобусе", train: "на электричке" };
let optionsCache = null;
const options = async () => (optionsCache ||= await api("/api/profile/options", { auth: false }));

function card(inner, cls = "") {
  return `<div class="acc-card ${cls}">${inner}</div>`;
}

function field(name, label, type = "text", attrs = "") {
  return `<label class="fld"><span>${label}</span><input name="${name}" type="${type}" ${attrs}></label>`;
}

function formError(form, msg) {
  const box = form.querySelector(".form-msg");
  box.className = "form-msg err";
  box.textContent = msg;
}

function formOk(form, msg) {
  const box = form.querySelector(".form-msg");
  box.className = "form-msg ok";
  box.textContent = msg;
}

async function submitting(form, fn) {
  const btn = form.querySelector("button[type=submit]");
  btn.disabled = true;
  try { await fn(); } catch (e) { formError(form, e.message); } finally { btn.disabled = false; }
}

function chipGroup(name, opts, selected, multi) {
  const sel = new Set(Array.isArray(selected) ? selected : [selected]);
  return `<div class="chips pick" data-name="${name}" data-multi="${multi ? 1 : 0}" role="group">` +
    Object.entries(opts).map(([k, v]) => `<button type="button" class="chip" data-value="${esc(k)}" aria-pressed="${sel.has(k)}">${esc(v)}</button>`).join("") +
    "</div>";
}

function bindChips(root) {
  root.querySelectorAll(".pick").forEach((g) => g.addEventListener("click", (e) => {
    const b = e.target.closest(".chip");
    if (!b) return;
    const on = b.getAttribute("aria-pressed") !== "true";
    if (g.dataset.multi !== "1") g.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", "false"));
    b.setAttribute("aria-pressed", String(on));
  }));
}

const picked = (root, name) => [...root.querySelectorAll(`.pick[data-name="${name}"] .chip[aria-pressed="true"]`)].map((b) => b.dataset.value);

// ---------- вход и регистрация ----------

export function loginPage(el, { params, navigate, mascot }) {
  const notice = params.get("verify") === "expired" ? "Ссылка из письма устарела. Войдите или запросите новое письмо." : params.get("reset") === "ok" ? "Пароль изменён. Войдите с новым паролем." : "";
  el.innerHTML = card(`
    <div class="acc-head"><div class="acc-art">${mascot}</div><div><h1>Вход</h1><p>Чтобы сохранять поездки и получать идеи под ваши интересы.</p></div></div>
    <form id="f" novalidate>
      ${field("email", "Почта", "email", 'autocomplete="email" required')}
      ${field("password", "Пароль", "password", 'autocomplete="current-password" required')}
      <p class="form-msg${notice ? " ok" : ""}" role="alert">${esc(notice)}</p>
      <button class="go" type="submit">Войти</button>
      <p class="acc-links"><a href="#/forgot">Забыли пароль?</a> · <a href="#/register">Регистрация</a></p>
    </form>`, "narrow");
  const f = el.querySelector("#f");
  f.addEventListener("submit", (e) => {
    e.preventDefault();
    submitting(f, async () => {
      try {
        const user = await login(f.email.value.trim(), f.password.value);
        navigate(params.get("next") || (user.onboarded ? "/recommendations" : "/onboarding"));
      } catch (err) {
        if (err.status === 403) {
          sessionStorage.setItem("amba-pending-email", f.email.value.trim());
          formError(f, err.message);
          f.querySelector(".form-msg").insertAdjacentHTML("beforeend", ' <a href="#/check-email">Отправить письмо ещё раз</a>');
        } else throw err;
      }
    });
  });
}

export function registerPage(el, { navigate, mascot }) {
  el.innerHTML = card(`
    <div class="acc-head"><div class="acc-art">${mascot}</div><div><h1>Регистрация</h1><p>Минута — и Амба будет подбирать поездки под вас.</p></div></div>
    <form id="f" novalidate>
      ${field("name", "Как к вам обращаться", "text", 'autocomplete="given-name" maxlength="80"')}
      ${field("email", "Почта", "email", 'autocomplete="email" required')}
      ${field("password", "Пароль", "password", 'autocomplete="new-password" required minlength="8"')}
      <p class="hint">Минимум 8 символов, буквы и цифры.</p>
      <p class="form-msg" role="alert"></p>
      <button class="go" type="submit">Зарегистрироваться</button>
      <p class="acc-links">Уже есть аккаунт? <a href="#/login">Войти</a></p>
    </form>`, "narrow");
  const f = el.querySelector("#f");
  f.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!validPassword(f.password.value)) return formError(f, "Пароль: минимум 8 символов, буквы и цифры");
    submitting(f, async () => {
      const email = f.email.value.trim();
      await api("/api/auth/register", { method: "POST", auth: false, body: { email, password: f.password.value, name: f.name.value.trim() } });
      sessionStorage.setItem("amba-pending-email", email);
      navigate("/check-email");
    });
  });
}

export function checkEmailPage(el, { mascot }) {
  const email = sessionStorage.getItem("amba-pending-email") || "";
  el.innerHTML = card(`
    <div class="acc-head"><div class="acc-art">${mascot}</div><div><h1>Проверьте почту</h1>
      <p>Мы отправили ссылку для подтверждения${email ? ` на <b>${esc(email)}</b>` : ""}. Она действует 24 часа. Письма нет — загляните в «Спам».</p></div></div>
    <form id="f" novalidate>
      ${field("email", "Почта", "email", `value="${esc(email)}" required`)}
      <p class="form-msg" role="alert"></p>
      <button class="ghost-btn" type="submit">Отправить письмо ещё раз</button>
    </form>`, "narrow");
  const f = el.querySelector("#f");
  f.addEventListener("submit", (e) => {
    e.preventDefault();
    submitting(f, async () => {
      const d = await api("/api/auth/resend", { method: "POST", auth: false, body: { email: f.email.value.trim() } });
      formOk(f, d.message);
    });
  });
}

export function forgotPage(el) {
  el.innerHTML = card(`<h1>Сброс пароля</h1><p class="lead-s">Пришлём ссылку, по которой можно задать новый пароль.</p>
    <form id="f" novalidate>${field("email", "Почта", "email", 'autocomplete="email" required')}
      <p class="form-msg" role="alert"></p><button class="go" type="submit">Прислать ссылку</button>
      <p class="acc-links"><a href="#/login">Вспомнили пароль?</a></p></form>`, "narrow");
  const f = el.querySelector("#f");
  f.addEventListener("submit", (e) => {
    e.preventDefault();
    submitting(f, async () => {
      const d = await api("/api/auth/forgot", { method: "POST", auth: false, body: { email: f.email.value.trim() } });
      formOk(f, d.message);
    });
  });
}

export function resetPage(el, { params, navigate }) {
  el.innerHTML = card(`<h1>Новый пароль</h1>
    <form id="f" novalidate>${field("password", "Новый пароль", "password", 'autocomplete="new-password" required minlength="8"')}
      <p class="hint">Минимум 8 символов, буквы и цифры.</p><p class="form-msg" role="alert"></p>
      <button class="go" type="submit">Сохранить пароль</button></form>`, "narrow");
  const f = el.querySelector("#f");
  f.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!validPassword(f.password.value)) return formError(f, "Пароль: минимум 8 символов, буквы и цифры");
    submitting(f, async () => {
      await api("/api/auth/reset", { method: "POST", auth: false, body: { token: params.get("token") || "", password: f.password.value } });
      navigate("/login?reset=ok");
    });
  });
}

// ---------- анкета ----------

export async function onboardingPage(el, { navigate, welcome }) {
  const [o, u] = [await options(), currentUser()];
  el.innerHTML = card(`
    <h1>${welcome ? "Почта подтверждена! 🎉" : "Ваши интересы"}</h1>
    <p class="lead-s">${welcome ? "Расскажите о себе — Амба подберёт поездки и будет учитывать это в каждом плане." : "Амба учитывает это в рекомендациях и в каждом плане."}</p>
    <form id="f" class="quiz">
      <fieldset><legend>Что любите в поездках?</legend>${chipGroup("interests", o.interests, u.interests, true)}</fieldset>
      <fieldset><legend>На чём удобно ездить?</legend>${chipGroup("transport", o.transport, u.transport, true)}</fieldset>
      <fieldset><legend>С кем обычно путешествуете?</legend>${chipGroup("companions", o.companions, u.companions, false)}</fieldset>
      <fieldset><legend>Бюджет</legend>${chipGroup("budget", o.budget, u.budget, false)}</fieldset>
      <fieldset><legend>Темп</legend>${chipGroup("pace", o.pace, u.pace, false)}</fieldset>
      ${field("home_city", "Откуда стартуете", "text", `value="${esc(u.home_city || "Владивосток")}" maxlength="80"`)}
      <p class="form-msg" role="alert"></p>
      <div class="q-actions"><button class="go" type="submit">Сохранить и показать идеи</button>
        ${welcome ? '<a class="ghost-btn" href="#/">Позже</a>' : ""}</div>
    </form>`);
  const f = el.querySelector("#f");
  bindChips(f);
  f.addEventListener("submit", (e) => {
    e.preventDefault();
    submitting(f, async () => {
      const body = { interests: picked(f, "interests"), transport: picked(f, "transport"), companions: picked(f, "companions")[0] || "",
        budget: picked(f, "budget")[0] || "", pace: picked(f, "pace")[0] || "", home_city: f.home_city.value.trim() || "Владивосток", onboarded: true };
      updateUser(await api("/api/me", { method: "PATCH", body }));
      navigate("/recommendations");
    });
  });
}

// ---------- рекомендации ----------

export async function recommendationsPage(el, { startPlan }) {
  el.innerHTML = '<div class="acc-loading">Подбираем идеи…</div>';
  const r = await api("/api/recommendations");
  const u = currentUser();
  const ideas = r.trips.map((t) => `<article class="idea">
      <div class="idea-emoji" aria-hidden="true">${esc(t.emoji)}</div>
      <h3>${esc(t.title)}</h3>
      <p class="idea-meta">${esc(t.area)} · ${t.days === 1 ? "1 день" : `${t.days} дня`}</p>
      ${t.why.length ? `<p class="idea-why">Подходит: ${t.why.map(esc).join(", ")}</p>` : ""}
      <button class="go small" type="button" data-q="${esc(t.query)}">Собрать план</button>
    </article>`).join("");
  const places = r.places.map((p) => `<li><a href="${esc(p.map_url)}" target="_blank" rel="noopener noreferrer"><b>${esc(p.name)}</b></a>
      <span>${esc(p.area)}</span><p>${esc(p.desc)}</p></li>`).join("");
  el.innerHTML = `
    <header class="page-head"><h1>Идеи для вас${u.name ? `, ${esc(u.name)}` : ""}</h1>
      <p>${r.onboarded ? "Подобрано по вашей анкете и прошлым поездкам." : 'Заполните <a href="#/onboarding">анкету</a> — идеи станут точнее.'} <a href="#/onboarding">Изменить интересы</a></p></header>
    <div class="ideas">${ideas}</div>
    <h2 class="sec-title">Места под ваши интересы</h2>
    <ul class="places">${places}</ul>`;
  el.querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => startPlan(b.dataset.q)));
}

// ---------- поездки ----------

export async function tripsPage(el, { navigate }) {
  el.innerHTML = '<div class="acc-loading">Загружаем поездки…</div>';
  let trips = await api("/api/trips");
  let onlyFav = false;
  const draw = () => {
    const list = onlyFav ? trips.filter((t) => t.favorite) : trips;
    el.innerHTML = `<header class="page-head"><h1>Мои поездки</h1>
        <div class="seg" role="radiogroup" aria-label="Фильтр"><button type="button" class="seg-btn" role="radio" aria-checked="${!onlyFav}" data-f="all">Все</button>
        <button type="button" class="seg-btn" role="radio" aria-checked="${onlyFav}" data-f="fav">Избранные</button></div></header>
      ${list.length ? `<ul class="trips">${list.map((t) => `<li class="trip">
        <a class="trip-main" href="#/trips/${esc(t.id)}"><b>${esc(t.title)}</b>
          <span class="trip-meta">${esc(t.area)} · ${t.start_date ? esc(humanDate(t.start_date)) : ""}${t.days ? ` · ${t.days} дн.` : ""}${TRANSPORT_RU[t.transport] ? ` · ${TRANSPORT_RU[t.transport]}` : ""}</span>
          <span class="trip-q">«${esc(t.query)}»</span></a>
        <span class="trip-badge ${t.converges ? "ok" : "bad"}">${t.converges ? "сходится" : "есть замечания"}</span>
        <button type="button" class="icon-btn" data-fav="${esc(t.id)}" aria-pressed="${t.favorite}" aria-label="В избранное">${t.favorite ? "★" : "☆"}</button>
        <button type="button" class="icon-btn" data-del="${esc(t.id)}" aria-label="Удалить поездку">✕</button>
      </li>`).join("")}</ul>` : `<div class="empty">${onlyFav ? "В избранном пока пусто." : 'Поездок пока нет. <a href="#/">Спланируйте первую</a> — она сохранится здесь.'}</div>`}`;
    el.querySelectorAll("[data-f]").forEach((b) => b.addEventListener("click", () => { onlyFav = b.dataset.f === "fav"; draw(); }));
    el.querySelectorAll("[data-fav]").forEach((b) => b.addEventListener("click", async () => {
      const t = trips.find((x) => x.id === b.dataset.fav);
      Object.assign(t, await api(`/api/trips/${t.id}`, { method: "PATCH", body: { favorite: !t.favorite } }));
      draw();
    }));
    el.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
      if (!confirm("Удалить поездку из истории?")) return;
      await api(`/api/trips/${b.dataset.del}`, { method: "DELETE" });
      trips = trips.filter((x) => x.id !== b.dataset.del);
      draw();
    }));
  };
  draw();
}

// ---------- профиль ----------

export async function profilePage(el, { navigate }) {
  const u = currentUser();
  const o = await options();
  const pref = [
    u.interests?.length && `Интересы: ${u.interests.map((k) => o.interests[k]).join(", ")}`,
    u.transport?.length && `Транспорт: ${u.transport.map((k) => o.transport[k]).join(", ")}`,
    u.companions && `С кем: ${o.companions[u.companions]}`, u.budget && `Бюджет: ${o.budget[u.budget]}`, u.pace && `Темп: ${o.pace[u.pace]}`,
  ].filter(Boolean);
  el.innerHTML = `<header class="page-head"><h1>Профиль</h1></header>
    <div class="acc-grid">
      ${card(`<h2>Данные</h2><form id="fp">${field("name", "Имя", "text", `value="${esc(u.name)}" maxlength="80"`)}
        <label class="fld"><span>Почта</span><input value="${esc(u.email)}" disabled></label>
        ${field("home_city", "Откуда стартуете", "text", `value="${esc(u.home_city)}" maxlength="80"`)}
        <p class="form-msg" role="alert"></p><button class="go small" type="submit">Сохранить</button></form>`)}
      ${card(`<h2>Анкета</h2>${pref.length ? `<ul class="pref">${pref.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>` : '<p class="lead-s">Анкета не заполнена.</p>'}
        <a class="ghost-btn" href="#/onboarding">Изменить интересы</a>`)}
      ${card(`<h2>Смена пароля</h2><form id="fw" novalidate>${field("current", "Текущий пароль", "password", 'autocomplete="current-password"')}
        ${field("next", "Новый пароль", "password", 'autocomplete="new-password"')}<p class="hint">Другие устройства выйдут из аккаунта.</p>
        <p class="form-msg" role="alert"></p><button class="go small" type="submit">Сменить пароль</button></form>`)}
      ${card(`<h2>Аккаунт</h2><p class="lead-s">С нами с ${esc(new Date(u.created_at).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" }))}.</p>
        <div class="q-actions"><button class="ghost-btn" type="button" id="out">Выйти</button>
        <button class="ghost-btn danger" type="button" id="del">Удалить аккаунт</button></div>`)}
    </div>`;
  const fp = el.querySelector("#fp");
  fp.addEventListener("submit", (e) => {
    e.preventDefault();
    submitting(fp, async () => {
      updateUser(await api("/api/me", { method: "PATCH", body: { name: fp.name.value.trim(), home_city: fp.home_city.value.trim() } }));
      formOk(fp, "Сохранено");
    });
  });
  const fw = el.querySelector("#fw");
  fw.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!validPassword(fw.next.value)) return formError(fw, "Новый пароль: минимум 8 символов, буквы и цифры");
    submitting(fw, async () => {
      setSession(await api("/api/me/password", { method: "POST", body: { current_password: fw.current.value, new_password: fw.next.value } }));
      fw.reset();
      formOk(fw, "Пароль изменён");
    });
  });
  el.querySelector("#out").addEventListener("click", async () => { await logout(); navigate("/"); });
  el.querySelector("#del").addEventListener("click", async () => {
    if (!confirm("Удалить аккаунт и все сохранённые поездки? Это нельзя отменить.")) return;
    await api("/api/me", { method: "DELETE" });
    await logout();
    navigate("/");
  });
}
