/**
 * The provider boundary contract.
 *
 * The architectural rule this file encodes:
 *
 *   Demo and live providers may obtain data differently, but everything above
 *   the provider boundary receives the same contract.
 *
 * These types mirror the backend's Pydantic models and service return shapes.
 * They are the compile-time half of the guarantee; the runtime half is
 * `backend/tests/test_demo_fixtures.py` (fixtures validate against the real
 * models) and the provider-contract test (both providers return these shapes).
 *
 * Deliberately plain `.d.ts` rather than Zod or a generated OpenAPI client —
 * one boundary, two implementations, and a checked type is proportionate. If
 * more provider-boundary bugs show up, revisit.
 */

export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "REVIEW";
export type AlertSeverity = "CRITICAL" | "WARNING" | "INFO";

/** Mirrors backend `app/models/resource.py::Resource`. */
export interface Resource {
  resource_type: string;
  resource_id: string;
  name: string | null;
  region: string;
  status: string;
  risk_level: RiskLevel;
  monthly_cost_risk: string;
  suggested_action: string;
  account_id: string | null;
  account_label: string | null;
  details: Record<string, unknown> | null;
  estimated_monthly_cost: number | null;
  cost_currency: string;
  cost_source: string | null;
}

/** Mirrors backend `app/models/alert.py::Alert`. */
export interface Alert {
  id: string;
  severity: AlertSeverity;
  rule: string;
  title: string;
  message: string;
  resource_type: string;
  resource_id: string;
  region: string;
  risk_level: string;
  estimated_monthly_cost: number | null;
}

export interface ScanSummary {
  total_resources: number;
  by_risk_level: Partial<Record<RiskLevel, number>>;
  estimated_monthly_cost: number;
}

/** A saved scan, as `GET /scans/{id}` returns it. */
export interface Scan {
  scan_id: string;
  created_at: string;
  summary: ScanSummary;
  resources: Resource[];
}

/** `GET /scan` — a scan plus the alerts derived from it. */
export interface ScanResult extends Scan {
  alerts?: Alert[];
  persisted?: boolean;
}

export interface DiffCounts {
  added: number;
  removed: number;
  changed: number;
  unchanged: number;
}

export interface ScanListItem {
  scan_id: string;
  created_at: string;
  resource_count: number;
  summary: ScanSummary;
  /** null for the earliest scan, which has no predecessor. */
  vs_previous: DiffCounts | null;
}

export interface ScanMeta {
  scan_id: string;
  created_at: string;
  summary: ScanSummary;
}

/**
 * One changed resource. Note the shape: the resource is nested under
 * `resource`, and `changes` is keyed by field name — NOT a flat resource with
 * an array. Getting this wrong crashed the demo's compare view once already.
 */
export interface ChangedResource {
  resource: Resource;
  changes: Record<string, { from: unknown; to: unknown }>;
}

/** Mirrors `diff_service.diff_scans`. */
export interface ScanDiff {
  from: ScanMeta;
  to: ScanMeta;
  added: Resource[];
  removed: Resource[];
  changed: ChangedResource[];
  summary: DiffCounts;
}

export interface AwsAccount {
  account_id: string;
  name: string;
  role_arn: string;
  external_id?: string | null;
  regions?: string[] | null;
  created_at?: string;
}

/**
 * What a surface is allowed to offer. Panels consult these rather than asking
 * "am I in demo mode?", so adding a surface means adding a provider.
 */
export interface Capabilities {
  liveScan: boolean;
  history: boolean;
  accountsAdmin: boolean;
  team: boolean;
  billing: boolean;
  cleanupExecute: boolean;
}

/** Every provider must satisfy this, however it obtains the data. */
export interface ScanProvider {
  mode: "api" | "demo";
  capabilities: Capabilities;

  runScan(): Promise<ScanResult>;
  listScans(limit?: number): Promise<{ scans: ScanListItem[] }>;
  getScan(scanId: string): Promise<Scan>;
  compareScans(fromId: string, toId: string): Promise<ScanDiff>;

  listAccounts(): Promise<{ accounts: AwsAccount[] }>;
  createAccount(account: Partial<AwsAccount>): Promise<unknown>;
  deleteAccount(accountId: string): Promise<unknown>;

  getMe(): Promise<{ tenant_id: string; user_id: string; role: string; name?: string }>;
  listUsers(): Promise<{ users: unknown[] }>;
  createUser(user: unknown): Promise<unknown>;
  deleteUser(userId: string): Promise<unknown>;

  getBilling(): Promise<unknown>;
  setPlan(plan: string): Promise<unknown>;
  startCheckout(): Promise<{ url: string }>;

  getCleanupActions(): Promise<{ enabled: boolean; actions: unknown[]; not_supported: unknown[] }>;
  getCleanupAudit(limit?: number): Promise<{ entries: unknown[] }>;
  executeCleanup(request: unknown): Promise<unknown>;
}
