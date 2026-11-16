import type { DebateScript, PresetInfo, SessionInfo } from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = body?.detail;
    const message = Array.isArray(detail)
      ? detail.map((d: { loc: unknown[]; msg: string }) => `${d.loc.slice(1).join(".")}: ${d.msg}`).join("; ")
      : (detail ?? res.statusText);
    throw new Error(`${res.status}: ${message}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  presets: () => request<PresetInfo[]>("/api/presets"),
  preset: (id: string) => request<DebateScript>(`/api/presets/${encodeURIComponent(id)}`),
  createSession: (script: DebateScript) =>
    request<SessionInfo>("/api/sessions", { method: "POST", body: JSON.stringify(script) }),
  session: (id: string) => request<SessionInfo>(`/api/sessions/${encodeURIComponent(id)}`),
};

export function sessionSocketUrl(sessionId: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws/sessions/${encodeURIComponent(sessionId)}`;
}

export function commandId(): string {
  return crypto.randomUUID().slice(0, 8);
}
