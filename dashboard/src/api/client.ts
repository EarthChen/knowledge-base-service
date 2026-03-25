const API_BASE = "/api/v1";
const STORAGE_KEY = "kb_api_token";

export function getToken(): string {
  return localStorage.getItem(STORAGE_KEY) || "";
}

export function setToken(value: string) {
  if (value) localStorage.setItem(STORAGE_KEY, value);
  else localStorage.removeItem(STORAGE_KEY);
}

function authHeaders(): Record<string, string> {
  const t = getToken();
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (t) h.Authorization = `Bearer ${t}`;
  return h;
}

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export async function api<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = path.startsWith("http") ? path : API_BASE + path;
  const res = await fetch(url, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers as Record<string, string>) },
  });
  const text = await res.text();
  let data: unknown;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    const d = data as Record<string, unknown> | null;
    let msg = res.statusText;
    if (d && typeof d.detail === "string") msg = d.detail;
    else if (d && d.detail != null) msg = JSON.stringify(d.detail);
    else if (d && d.error) msg = String(d.error);
    throw new ApiError(msg || "Request failed", res.status, data);
  }
  return data as T;
}
