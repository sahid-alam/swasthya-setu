const TOKEN_KEY = "setu.token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t: string | null) =>
  t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY);

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(`/api/v1${path}`, {
    ...init,
    headers: {
      ...(init.body instanceof URLSearchParams
        ? {}
        : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail ?? res.statusText);
  }
  return res.json();
}

export async function login(phone: string, password: string) {
  const body = new URLSearchParams({ username: phone, password });
  const out = await api<{ access_token: string; role: string }>("/auth/token", {
    method: "POST",
    body,
  });
  setToken(out.access_token);
  return out;
}

/** Role carried by the current token. Patients get their own endpoints, which scope
 *  to the token holder rather than trusting an id in the URL. */
export function tokenRole(): string | null {
  const token = getToken();
  if (!token) return null;
  try {
    return JSON.parse(atob(token.split(".")[1])).role ?? null;
  } catch {
    return null;
  }
}

export const isPatient = () => tokenRole() === "PATIENT";

/** Sign out, back to the login this token came from. A hard navigation rather than a
 *  router push on purpose: it drops the in-memory TanStack cache with it, so one
 *  patient's queue cannot survive into the next patient's session on a shared kiosk. */
export function logout() {
  const target = isPatient() ? "/patient" : "/login";
  setToken(null);
  location.href = target;
}

/** Dashboard event stream. Token rides the query string — WebSockets take no headers.
 *  The endpoint also filters on hospital_id; 1D passes it once there is a switcher. */
export function dashboardSocket(): WebSocket {
  const params = new URLSearchParams({ token: getToken() ?? "" });
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(`${scheme}://${location.host}/ws/dashboard?${params}`);
}
