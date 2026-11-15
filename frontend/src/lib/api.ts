/**
 * Cliente HTTP da API do Corpo Sano.
 * - Access token apenas em memória (nunca em localStorage);
 * - Refresh token em cookie httpOnly (renovação automática e rotativa);
 * - Erros convertidos em mensagens claras em português.
 */
export class ApiError extends Error {
  status: number;
  code?: string;
  details?: unknown;
  constructor(message: string, status: number, code?: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onSessionEnd: ((reason: string) => void) | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}
export function hasAccessToken() {
  return !!accessToken;
}
export function onSessionExpired(cb: (reason: string) => void) {
  onSessionEnd = cb;
}

const BASE = "/api/v1";

export async function refreshSession(): Promise<boolean> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const r = await fetch(`${BASE}/auth/refresh`, { method: "POST", credentials: "same-origin" });
        // 204 = nenhuma sessão salva neste navegador (não é erro)
        if (!r.ok || r.status === 204) return false;
        const data = await r.json();
        setAccessToken(data.access_token);
        return true;
      } catch {
        return false;
      } finally {
        setTimeout(() => (refreshing = null), 0);
      }
    })();
  }
  return refreshing;
}

type Options = {
  method?: string;
  body?: unknown;
  form?: FormData;
  params?: Record<string, unknown>;
  raw?: boolean;
};

function buildUrl(path: string, params?: Record<string, unknown>) {
  const url = new URL(path.startsWith("http") ? path : `${BASE}${path}`, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
    });
  }
  return url.pathname + url.search;
}

export async function api<T = any>(path: string, opts: Options = {}, retry = true): Promise<T> {
  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.params), {
      method: opts.method || (body ? "POST" : "GET"),
      headers,
      body,
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError("Sem conexão com o servidor. Verifique a internet e tente novamente.", 0);
  }
  if (res.status === 401 && retry && !path.startsWith("/auth/login")) {
    const ok = await refreshSession();
    if (ok) return api<T>(path, opts, false);
    let reason = "Sessão encerrada. Entre novamente.";
    try {
      reason = (await res.json()).detail || reason;
    } catch {
      /* corpo vazio */
    }
    setAccessToken(null);
    onSessionEnd?.(reason);
    throw new ApiError(reason, 401);
  }
  if (!res.ok) {
    let msg = `Erro ${res.status}`;
    let code: string | undefined;
    let details: unknown;
    try {
      const data = await res.json();
      msg = data.detail || msg;
      code = data.code;
      details = data.details;
    } catch {
      /* resposta sem JSON */
    }
    if (res.status === 403 && code === "troca_senha_obrigatoria") onSessionEnd?.("troca_senha");
    throw new ApiError(msg, res.status, code, details);
  }
  if (opts.raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  const ctype = res.headers.get("content-type") || "";
  return (ctype.includes("json") ? res.json() : res.text()) as Promise<T>;
}

/** Baixa um arquivo autenticado e dispara o download no navegador. */
export async function download(path: string, params?: Record<string, unknown>, fallbackName = "arquivo") {
  const res = await api<Response>(path, { params, raw: true });
  const blob = await res.blob();
  const disp = res.headers.get("content-disposition") || "";
  const match = /filename="?([^";]+)"?/.exec(disp);
  const name = match ? match[1] : fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export const get = <T = any>(path: string, params?: Record<string, unknown>) => api<T>(path, { params });
export const post = <T = any>(path: string, body?: unknown, params?: Record<string, unknown>) =>
  api<T>(path, { method: "POST", body: body ?? {}, params });
export const put = <T = any>(path: string, body?: unknown) => api<T>(path, { method: "PUT", body });
export const del = <T = any>(path: string) => api<T>(path, { method: "DELETE" });
export const upload = <T = any>(path: string, form: FormData) => api<T>(path, { method: "POST", form });
