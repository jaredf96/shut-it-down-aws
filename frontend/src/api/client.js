// Thin API client for the backend. Override the base URL with a Vite env var
// (VITE_API_BASE_URL) when you deploy the backend somewhere other than local.
const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// Optional API key for SaaS mode. Left unset, the backend runs as the default
// tenant (local dev needs no key).
const API_KEY = import.meta.env.VITE_API_KEY;

function authHeaders() {
  return API_KEY ? { "X-API-Key": API_KEY } : {};
}

async function getJSON(path) {
  const res = await fetch(`${BASE_URL}${path}`, { headers: authHeaders() });
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

async function sendJSON(method, path, body) {
  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
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

// Runs a single scanner by slug, e.g. "ec2". Returns { count, resources }.
export function scanOne(slug) {
  return getJSON(`/scan/${slug}`);
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

// --- Billing ---

export function getBilling() {
  return getJSON("/billing");
}

export function setPlan(plan) {
  return sendJSON("POST", "/billing/plan", { plan });
}

export function startCheckout() {
  return sendJSON("POST", "/billing/checkout");
}

// --- Team / users ---

// Current principal: { tenant_id, user_id, role, name }.
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
