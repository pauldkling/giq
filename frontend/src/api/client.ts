// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

/* The one way this page talks to giq. Every request carries the shared
   token when there is one, and every failure becomes an ApiError with the
   status and the server's `detail`, so a view never parses a raw Response.

   Token: arriving as ?token=… is how the operator opens the dashboard on a
   token-guarded rig. It moves to sessionStorage at once, so the secret
   leaves the address bar (and the history entry) and does not outlive the
   tab, and goes out as X-Giq-Token on every call from here. */

const TOKEN_KEY = "giq-token";

function captureToken(): string {
  try {
    const url = new URL(window.location.href);
    const fromUrl = url.searchParams.get("token");
    if (fromUrl) {
      sessionStorage.setItem(TOKEN_KEY, fromUrl);
      url.searchParams.delete("token");
      history.replaceState(history.state, "", url.toString());
    }
    return sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return ""; // storage disabled: the header simply goes unsent
  }
}

let token = typeof window === "undefined" ? "" : captureToken();

/** Whether a token is in use (for the access chip), never the token itself. */
export const hasToken = (): boolean => token !== "";

/** Replace the token (e.g. after a 401, from a prompt). Empty clears it. */
export function setToken(next: string): void {
  token = next;
  try {
    if (next) sessionStorage.setItem(TOKEN_KEY, next);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* in-memory only */
  }
}

/** An HTTP failure, or a network error (status 0), with the server's detail. */
export class ApiError extends Error {
  readonly status: number;
  /** FastAPI's `detail`: usually a string, sometimes an object (e.g. /llm/endpoint's 503). */
  readonly detail: unknown;
  /** The whole parsed body, for endpoints that return more than `detail`. */
  readonly body: unknown;

  constructor(status: number, detail: unknown, body?: unknown) {
    super(typeof detail === "string" ? detail : status ? `HTTP ${status}` : "network error");
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.body = body;
  }
}

/** The error's message for display: the server's detail text when it sent one. */
export function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (typeof err.detail === "string") return err.detail;
    if (err.detail != null) return JSON.stringify(err.detail);
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return String(err);
}

/* Residency and binding changes that would over-commit a card come back 409
   with "force=true" in the detail: the change is refused but may be
   insisted on. Views confirm with the operator (showing the detail) and
   repeat the call with force: true. A 409 without it — two LLMs on one card —
   is a hard no and must not offer the override. */
export function needsForce(err: unknown): err is ApiError {
  return (
    err instanceof ApiError &&
    err.status === 409 &&
    typeof err.detail === "string" &&
    /force=true/.test(err.detail)
  );
}

export const isAbort = (err: unknown): boolean =>
  err instanceof DOMException && err.name === "AbortError";

function headers(extra?: HeadersInit): Headers {
  const h = new Headers(extra);
  if (token) h.set("X-Giq-Token", token);
  return h;
}

async function parseBody(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/** fetch() with the token, turning non-2xx into ApiError. Returns the Response for the caller to read. */
export async function request(path: string, init: RequestInit = {}): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers: headers(init.headers) });
  } catch (e) {
    if (isAbort(e)) throw e;
    throw new ApiError(0, e instanceof Error ? e.message : String(e));
  }
  if (!res.ok) {
    const body = await parseBody(res);
    const detail =
      body && typeof body === "object" && "detail" in body
        ? (body as { detail: unknown }).detail
        : body;
    throw new ApiError(res.status, detail, body);
  }
  return res;
}

type Opts = { signal?: AbortSignal };

export async function getJSON<T>(path: string, opts: Opts = {}): Promise<T> {
  const res = await request(path, { signal: opts.signal });
  return (await res.json()) as T;
}

export async function postJSON<T>(path: string, body?: unknown, opts: Opts = {}): Promise<T> {
  const res = await request(path, {
    method: "POST",
    signal: opts.signal,
    ...(body === undefined
      ? {}
      : { headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
  });
  return (await parseBody(res)) as T;
}

export async function del<T>(path: string, opts: Opts = {}): Promise<T> {
  const res = await request(path, { method: "DELETE", signal: opts.signal });
  return (await parseBody(res)) as T;
}

/** Multipart upload (audio transcription and embeddings take files). */
export async function postForm<T>(path: string, form: FormData, opts: Opts = {}): Promise<T> {
  const res = await request(path, { method: "POST", body: form, signal: opts.signal });
  return (await parseBody(res)) as T;
}

/** POST returning a binary body (text-to-speech audio). */
export async function postBlob(path: string, body: unknown, opts: Opts = {}): Promise<Blob> {
  const res = await request(path, {
    method: "POST",
    signal: opts.signal,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.blob();
}

/* Server-sent events from an OpenAI-style streaming endpoint, parsed by hand
   because EventSource cannot POST or set headers. Events are split on blank
   lines with the partial tail kept for the next chunk; only `data:` lines
   count; "[DONE]" ends the stream and non-JSON lines (keepalives) are
   skipped. An in-band {"error": …} — how giq reports a failure after the
   200 is already sent — throws as an ApiError. */
export async function* stream<T = unknown>(
  path: string,
  body: unknown,
  opts: Opts = {},
): AsyncGenerator<T, void, undefined> {
  const res = await request(path, {
    method: "POST",
    signal: opts.signal,
    headers: { "content-type": "application/json", accept: "text/event-stream" },
    body: JSON.stringify(body),
  });
  if (!res.body) return;
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += value;
      let cut: number;
      while ((cut = buf.indexOf("\n\n")) >= 0) {
        const event = buf.slice(0, cut);
        buf = buf.slice(cut + 2);
        for (const line of event.split("\n")) {
          if (!line.startsWith("data:")) continue;
          const data = line.slice(5).trim();
          if (!data || data === "[DONE]") continue;
          let parsed: unknown;
          try {
            parsed = JSON.parse(data);
          } catch {
            continue;
          }
          const err = (parsed as { error?: unknown } | null)?.error;
          if (err) {
            const msg =
              typeof err === "object" && "message" in err
                ? (err as { message: unknown }).message
                : err;
            throw new ApiError(
              res.status,
              typeof msg === "string" ? msg : "generation failed",
            );
          }
          yield parsed as T;
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
