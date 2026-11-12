import type { OfficeSnapshot } from './types';

export function getToken(): string {
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get('token');
  if (fromUrl) {
    sessionStorage.setItem('office-token', fromUrl);
    return fromUrl;
  }
  return sessionStorage.getItem('office-token') || '';
}

export function apiBase(): string {
  return (import.meta as any).env?.VITE_OFFICE_API || '';
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken()}`,
      ...(init.headers || {}),
    },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = (body && (body.message || body.error)) || `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return body as T;
}

export const api = {
  models: () => request<ModelSettings>('/api/settings/models'),
  saveModels: (models: Partial<Record<'claude' | 'codex' | 'agy', string>>) => request<ModelSettings>('/api/settings/models', {
    method: 'POST', body: JSON.stringify({ models }),
  }),
  state: (runId?: string) =>
    request<OfficeSnapshot>(`/api/state${runId ? `?run_id=${encodeURIComponent(runId)}` : ''}`),
  startRun: (body: { mode: 'discuss' | 'plan'; question: string; chair?: string; cwd?: string; files?: string[] }) =>
    request<{ ok: boolean; run_id: string; snapshot: OfficeSnapshot }>('/api/runs/start', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  approve: (runId: string, body: { writer?: string; create_pr?: boolean }) =>
    request<{ ok: boolean; approved: boolean; snapshot: OfficeSnapshot }>(
      `/api/runs/${encodeURIComponent(runId)}/approve`,
      { method: 'POST', body: JSON.stringify(body) },
    ),
  cancel: (runId: string) =>
    request<{ ok: boolean; snapshot: OfficeSnapshot }>(`/api/runs/${encodeURIComponent(runId)}/cancel`, {
      method: 'POST',
      body: '{}',
    }),
  resume: (runId: string) =>
    request<{ ok: boolean; snapshot: OfficeSnapshot }>(`/api/runs/${encodeURIComponent(runId)}/resume`, {
      method: 'POST',
      body: '{}',
    }),
};

export interface ModelSettings {
  busy: boolean;
  providers: Array<{ id: 'claude' | 'codex' | 'agy'; name: string; model: string; effort: string; options: Array<{ id: string; label: string }> }>;
}

export type WsMessage =
  | { type: 'snapshot'; data: OfficeSnapshot }
  | { type: 'events'; run_id: string; events: OfficeSnapshot['events']; snapshot: OfficeSnapshot }
  | { type: 'replay'; run_id: string; events: OfficeSnapshot['events'] }
  | { type: 'pong'; timestamp: number };

export function connectEvents(
  onMessage: (msg: WsMessage) => void,
  onStatus: (connected: boolean) => void,
): { send: (obj: unknown) => void; close: () => void } {
  let ws: WebSocket | null = null;
  let closed = false;
  let retry: number | undefined;

  const open = () => {
    const base = apiBase() || window.location.origin;
    const url = base.replace(/^http/, 'ws') + `/ws/events?token=${encodeURIComponent(getToken())}`;
    ws = new WebSocket(url);
    ws.onopen = () => onStatus(true);
    ws.onclose = () => {
      onStatus(false);
      if (!closed) retry = window.setTimeout(open, 2000);
    };
    ws.onmessage = (ev) => {
      try {
        onMessage(JSON.parse(ev.data));
      } catch {
        /* ignore malformed frames */
      }
    };
  };
  open();

  return {
    send: (obj) => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
    },
    close: () => {
      closed = true;
      if (retry) window.clearTimeout(retry);
      ws?.close();
    },
  };
}
