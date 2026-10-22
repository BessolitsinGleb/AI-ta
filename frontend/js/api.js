// Сессия: access-токен живёт только в памяти страницы, refresh — в httpOnly-cookie (JS его не видит).
const session = { token: null, issued: 0, ttl: 0, user: null };
const listeners = new Set();

export class ApiError extends Error {
  constructor(status, message, data) { super(message); this.status = status; this.data = data; }
}

const FIELD_HINTS = {
  email: "Проверьте адрес почты",
  password: "Пароль: минимум 8 символов, буквы и цифры",
  new_password: "Новый пароль: минимум 8 символов, буквы и цифры",
  name: "Имя — до 80 символов",
};

function errorText(status, data) {
  if (data?.errors?.length) return [...new Set(data.errors.map((e) => FIELD_HINTS[e.field] || "Проверьте введённые данные"))].join(". ");
  if (typeof data?.detail === "string") return data.detail;
  if (status === 429) return "Слишком много попыток. Попробуйте чуть позже.";
  return "Что-то пошло не так. Попробуйте ещё раз.";
}

function emit() { listeners.forEach((fn) => fn(session.user)); }
export function onAuth(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export const currentUser = () => session.user;

export function setSession(data) {
  session.token = data?.access_token || null;
  session.issued = Date.now();
  session.ttl = (data?.expires_in || 0) * 1000;
  session.user = data?.user || null;
  emit();
}

export function updateUser(user) { session.user = user; emit(); }

let refreshing = null;
export function refresh() {
  refreshing ||= fetch("/api/auth/refresh", { method: "POST", credentials: "same-origin" })
    .then(async (r) => { setSession(r.ok ? await r.json() : null); return r.ok; })
    .catch(() => false)
    .finally(() => { refreshing = null; });
  return refreshing;
}

// Перед долгим запросом (стрим плана) обновляем токен заранее, если он вот-вот истечёт.
export async function freshAuthHeader() {
  if (session.user && Date.now() - session.issued > session.ttl - 60_000) await refresh();
  return session.token ? { Authorization: `Bearer ${session.token}` } : {};
}

export async function api(path, { method = "GET", body, auth = true } = {}) {
  const send = () => fetch(path, {
    method,
    credentials: "same-origin",
    headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...(auth && session.token ? { Authorization: `Bearer ${session.token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  let r = await send();
  if (r.status === 401 && auth && session.user && (await refresh())) r = await send();
  const data = r.status === 204 ? null : await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(r.status, errorText(r.status, data), data);
  return data;
}

export async function login(email, password) {
  const data = await api("/api/auth/login", { method: "POST", body: { email, password }, auth: false });
  setSession(data);
  return data.user;
}

export async function logout() {
  await api("/api/auth/logout", { method: "POST", auth: false }).catch(() => {});
  setSession(null);
}

export function validPassword(pw) {
  return pw.length >= 8 && /\d/.test(pw) && /\p{L}/u.test(pw);
}
