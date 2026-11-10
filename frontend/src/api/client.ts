/**
 * API client (Plan §3.1). Same-origin cookies carry the server session (HTTP-only, so JS never
 * sees it). Unsafe methods send the session's CSRF token in `X-CSRF-Token`.
 * Errors carry a stable `code` that the UI translates under `apiErrors.*`.
 */

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function csrf(): string | null {
  return csrfToken;
}

/** Usability reporting (app/research.ts): told about network failures (0) and 5xx answers. */
let troubleReporter: ((status: number) => void) | null = null;
export function setTroubleReporter(fn: ((status: number) => void) | null): void {
  troubleReporter = fn;
}
function trouble(status: number): void {
  if (status === 0 || status >= 500) troubleReporter?.(status);
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly detail: Record<string, unknown> = {},
  ) {
    super(code);
    this.name = "ApiError";
  }
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (UNSAFE.has(method) && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    trouble(0);
    throw new ApiError(0, "network");
  }
  trouble(res.status);
  if (res.status === 204) return undefined as T;
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail) && "code" in detail) {
      const d = detail as Record<string, unknown>;
      throw new ApiError(res.status, String(d.code), d);
    }
    throw new ApiError(res.status, res.status === 422 ? "validation" : "unknown");
  }
  return data as T;
}

export const get = <T>(path: string) => api<T>("GET", path);
export const del = (path: string) => api<void>("DELETE", path);

/** One server-sent event from a streamed POST (lesson replies). */
export interface StreamEvent {
  event: string;
  data: Record<string, unknown>;
}

/**
 * POST and read a `text/event-stream` body as it arrives. Non-2xx answers throw `ApiError`
 * before any event is delivered, like `api()`.
 */
export async function postStream(
  path: string,
  body: unknown,
  onEvent: (ev: StreamEvent) => void,
): Promise<void> {
  const headers: Record<string, string> = {
    Accept: "text/event-stream",
    "Content-Type": "application/json",
  };
  if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, {
      method: "POST",
      headers,
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
  } catch {
    trouble(0);
    throw new ApiError(0, "network");
  }
  trouble(res.status);
  if (!res.ok) {
    const data: unknown = await res.json().catch(() => null);
    const detail = (data as { detail?: unknown } | null)?.detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail) && "code" in detail) {
      const d = detail as Record<string, unknown>;
      throw new ApiError(res.status, String(d.code), d);
    }
    throw new ApiError(res.status, res.status === 422 ? "validation" : "unknown");
  }
  const emit = (block: string) => {
    let event = "message";
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) event = line.slice(7).trim();
      else if (line.startsWith("data: ")) data += line.slice(6);
    }
    if (!data) return;
    try {
      onEvent({ event, data: JSON.parse(data) as Record<string, unknown> });
    } catch {
      /* ignore a malformed event */
    }
  };
  if (!res.body) {
    for (const block of (await res.text()).split("\n\n")) emit(block);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut = buffer.indexOf("\n\n");
    while (cut >= 0) {
      emit(buffer.slice(0, cut));
      buffer = buffer.slice(cut + 2);
      cut = buffer.indexOf("\n\n");
    }
  }
  if (buffer.trim()) emit(buffer);
}
export const post = <T>(path: string, body?: unknown) => api<T>("POST", path, body ?? {});
export const put = <T>(path: string, body?: unknown) => api<T>("PUT", path, body ?? {});
export const patch = <T>(path: string, body: unknown) => api<T>("PATCH", path, body);

/** i18n key for an error; falls back to a generic message. */
export function errorKey(err: unknown): string {
  if (err instanceof ApiError) return `apiErrors.${err.code}`;
  return "apiErrors.unknown";
}
