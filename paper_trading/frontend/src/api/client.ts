const BASE = process.env.REACT_APP_API_URL ?? "http://localhost:8000/api";
const API_KEY = process.env.REACT_APP_API_KEY ?? "";

function authHeaders(): HeadersInit {
  return API_KEY ? { "X-Api-Key": API_KEY } : {};
}

export async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error(`API ${path} returned ${res.status}`);
  return res.json();
}

export async function apiPost<T>(path: string): Promise<T> {
  return apiFetch<T>(path, { method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() } });
}

export async function apiPostBody<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
}

export async function apiDelete<T>(path: string): Promise<T> {
  return apiFetch<T>(path, { method: "DELETE", headers: { "Content-Type": "application/json", ...authHeaders() } });
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
}
