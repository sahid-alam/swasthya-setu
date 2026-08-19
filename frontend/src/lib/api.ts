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

/** Dashboard event stream. Token rides the query string — WebSockets take no headers.
 *  The endpoint also filters on hospital_id; 1D passes it once there is a switcher. */
export function dashboardSocket(): WebSocket {
  const params = new URLSearchParams({ token: getToken() ?? "" });
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(`${scheme}://${location.host}/ws/dashboard?${params}`);
}
