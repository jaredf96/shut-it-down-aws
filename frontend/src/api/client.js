// Thin API client for the backend. Override the base URL with a Vite env var
// (VITE_API_BASE_URL) when you deploy the backend somewhere other than local.
const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// Optional API key for a shared deployment. Left unset, the backend runs as
// the default workspace (a local install needs no key).
const API_KEY = import.meta.env.VITE_API_KEY;

function authHeaders() {
  return API_KEY ? { "X-API-Key": API_KEY } : {};
}

/**
 * A failed API call, unpacked.
 *
 * The backend answers errors with a structured envelope
 * (`app/main.py` -> ErrorEnvelopeMiddleware): a `detail` sentence, sometimes a
 * machine `error` code, and a `correlation_id` — which also comes back as the
 * `X-Correlation-ID` header on *every* response, envelope or not. Throwing all
 * of that away and reporting "Request failed: 403 Forbidden" hid the one
 * sentence that answers the user's question ("Cleanup actions are disabled in
 * this environment.") and stranded the id that makes the server log findable.
 *
 * `message` is a readable, terminated sentence on its own, because every
 * consumer renders `err.message` and nothing else. Components cannot test
 * `instanceof` this — they may not import this module (the provider boundary,
 * D5) — so the extra fields are plain optional properties, read defensively.
 *
 * The request URL is deliberately on neither: `VITE_API_BASE_URL` is
 * operator-supplied and could carry credentials, and a rendered error message
 * is the last place to put one. The API key travels as a header and never
 * touches this path at all.
 */
export class ApiError extends Error {
  /**
   * Annotated because `cause` carries no default, and without a declared type
   * `tsc` infers the options bag from the defaults alone and drops it.
   *
   * @param {string} message
   * @param {{
   *   status?: number | null,
   *   statusText?: string,
   *   detail?: string | null,
   *   code?: string | null,
   *   correlationId?: string | null,
   *   body?: string,
   *   cause?: unknown,
   * }} [options]
   */
  constructor(
    message,
    {
      status = null,
      statusText = "",
      detail = null,
      code = null,
      correlationId = null,
      body = "",
      cause,
    } = {}
  ) {
    // `{ cause }` is ES2022; an older engine ignores the options bag and
    // leaves `err.cause` undefined, which is exactly the degradation we want.
    super(message, cause === undefined ? undefined : { cause });
    this.name = "ApiError";
    this.status = status; // null when no response arrived at all
    this.statusText = statusText;
    this.detail = detail; // the backend's own sentence, verbatim, or null
    this.code = code; // "persistence_unavailable" | "internal_error" | "network_error" | null
    this.correlationId = correlationId; // quotable in a bug report
    this.body = body; // raw text, truncated — for the console, never rendered
  }
}

/**
 * `fetch`, with the one failure it reports as a bare `TypeError` turned into
 * an `ApiError` like every other. The backend not being up is the most common
 * failure this client sees, and "Failed to fetch" is neither a sentence nor
 * the same shape as every other rejection. No status is invented: no response
 * arrived, so there is none to report. The base URL stays out of the message —
 * `Dashboard.jsx` already supplies the reachability hint, and it is the
 * surface that knows it is not the demo.
 */
async function request(url, init) {
  try {
    return await fetch(url, init);
  } catch (cause) {
    throw new ApiError("Could not reach the API.", { code: "network_error", cause });
  }
}

const BODY_SNIPPET = 500;

/** Read a body without ever throwing: it may be empty, HTML, or cut short. */
async function readBody(res) {
  let text = "";
  try {
    text = await res.text();
  } catch {
    return { envelope: null, raw: "" }; // connection dropped mid-body
  }
  if (!text) return { envelope: null, raw: "" };
  const raw = text.slice(0, BODY_SNIPPET);
  try {
    const parsed = JSON.parse(text);
    const isEnvelope = parsed && typeof parsed === "object" && !Array.isArray(parsed);
    return { envelope: isEnvelope ? parsed : null, raw };
  } catch {
    return { envelope: null, raw }; // a proxy's HTML 502
  }
}

/**
 * FastAPI's `detail` is a string for a raised HTTPException and an array of
 * `{loc, msg, type}` for a 422 validation failure. Anything else means there
 * is no sentence to show, and the status line stands in.
 */
function detailToText(detail) {
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => (d && typeof d.msg === "string" ? d.msg : null)).filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  return null;
}

/** Callers concatenate this into longer sentences; give them a sentence. */
function terminated(text) {
  return /[.!?)]$/.test(text) ? text : `${text}.`;
}

async function apiError(res) {
  const { envelope, raw } = await readBody(res);
  const detail = detailToText(envelope?.detail);

  // Header first, body second. The header is on every response; the
  // `correlation_id` body field exists only on the two envelope paths, so a
  // plain HTTPException — the 400s, 403s and 404s, which is most refusals —
  // carries it in the header alone. `?.` because a stubbed Response may have
  // no headers at all.
  const correlationId =
    res.headers?.get?.("X-Correlation-ID") || envelope?.correlation_id || null;

  // Keep the old status line as the fallback, so an empty or non-JSON body
  // still reads as something. `statusText` is empty over HTTP/2.
  const fallback = `Request failed: ${res.status}${res.statusText ? ` ${res.statusText}` : ""}`;
  let message = terminated(detail || fallback);

  // A server-side fault is the only case where quoting an id gets the user
  // anywhere: its `detail` is generic by design ("Internal server error.") and
  // the next step is someone reading the log. A 403 refusal explains itself,
  // and a reference number on it would be noise.
  if (res.status >= 500 && correlationId) message += ` (ref ${correlationId})`;

  return new ApiError(message, {
    status: res.status,
    statusText: res.statusText || "",
    detail,
    code: typeof envelope?.error === "string" ? envelope.error : null,
    correlationId,
    body: raw,
  });
}

async function getJSON(path) {
  const res = await request(`${BASE_URL}${path}`, { headers: authHeaders() });
  if (!res.ok) {
    throw await apiError(res);
  }
  return res.json();
}

async function sendJSON(method, path, body) {
  const res = await request(`${BASE_URL}${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    throw await apiError(res);
  }
  return res.json();
}


export function getHealth() {
  return getJSON("/health");
}

// Runs every scanner. Returns { summary, resources }.
export function scanAll() {
  return getJSON("/scan");
}

// Lists recent saved scans (newest first). Returns { scans: [...] }.
// Throws if persistence is disabled (backend responds 503).
export function listScans(limit = 20) {
  return getJSON(`/scans?limit=${limit}`);
}

// Fetches one saved scan by id. Returns { scan_id, created_at, summary, resources }.
export function getScan(scanId) {
  return getJSON(`/scans/${encodeURIComponent(scanId)}`);
}

// Compares two saved scans (older `fromId` vs newer `toId`).
// Returns { from, to, added, removed, changed, summary }.
export function getDiff(fromId, toId) {
  const params = new URLSearchParams({ from_id: fromId, to_id: toId });
  return getJSON(`/scans/diff?${params.toString()}`);
}

// --- Multi-account ---

export function listAccounts() {
  return getJSON("/accounts");
}

export function createAccount(account) {
  return sendJSON("POST", "/accounts", account);
}

export function deleteAccount(accountId) {
  return sendJSON("DELETE", `/accounts/${encodeURIComponent(accountId)}`);
}

// --- Guided cleanup ---

// { enabled, actions: [...], not_supported: [...] }
export function getCleanupActions() {
  return getJSON("/cleanup/actions");
}

export function getCleanupAudit(limit = 20) {
  return getJSON(`/cleanup/audit?limit=${limit}`);
}

// request: { action, resource_id, confirm_resource_id, region, account_id?, dry_run }
export function executeCleanup(request) {
  return sendJSON("POST", "/cleanup/execute", request);
}

// --- Team / users ---

// Current principal: { workspace_id, user_id, role, name }.
export function getMe() {
  return getJSON("/me");
}

export function listUsers() {
  return getJSON("/users");
}

export function createUser(user) {
  return sendJSON("POST", "/users", user);
}

export function deleteUser(userId) {
  return sendJSON("DELETE", `/users/${encodeURIComponent(userId)}`);
}
