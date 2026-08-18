// Provider backed by curated fixtures. Makes no network calls, holds no
// credentials, and cannot reach the private API — the public demo is a static
// deployment, so isolation is a property of the deployment, not of this flag.
//
// Fixtures live in repo-root `demo-data/` so the backend test suite can
// validate them against the real Pydantic models and they can never silently
// drift from the API schema.
import accountsFixture from "@demo-data/accounts.json";
import alertsFixture from "@demo-data/alerts.json";
import currentScan from "@demo-data/current-scan.json";
import previousScan from "@demo-data/previous-scan.json";

// Long enough for the staged progress indicator to read as a real scan.
const SIMULATED_SCAN_MS = 3500;

const SCANS = [currentScan, previousScan]; // newest first, like the API

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Resource identity, matching the backend: the 4-tuple including account_id so
// the same id in two accounts is never conflated.
const identity = (r) => `${r.resource_type}|${r.region}|${r.resource_id}|${r.account_id ?? ""}`;

// Mirrors backend/app/services/diff_service.py: only status and risk_level are
// tracked, and each changed entry is {resource, changes} with `changes` keyed by
// field name. DiffView destructures exactly that shape.
const COMPARED_FIELDS = ["status", "risk_level"];

function diff(fromScan, toScan) {
  const before = new Map(fromScan.resources.map((r) => [identity(r), r]));
  const after = new Map(toScan.resources.map((r) => [identity(r), r]));

  const added = toScan.resources.filter((r) => !before.has(identity(r)));
  const removed = fromScan.resources.filter((r) => !after.has(identity(r)));

  const changed = [];
  let unchanged = 0;
  for (const [key, current] of after) {
    const prior = before.get(key);
    if (!prior) continue;
    const changes = {};
    for (const field of COMPARED_FIELDS) {
      if (prior[field] !== current[field]) {
        changes[field] = { from: prior[field], to: current[field] };
      }
    }
    if (Object.keys(changes).length) changed.push({ resource: current, changes });
    else unchanged += 1;
  }

  const meta = (s) => ({ scan_id: s.scan_id, created_at: s.created_at, summary: s.summary });
  return {
    from: meta(fromScan),
    to: meta(toScan),
    added,
    removed,
    changed,
    summary: {
      added: added.length,
      removed: removed.length,
      changed: changed.length,
      unchanged,
    },
  };
}

function notAvailable(what) {
  return () =>
    Promise.reject(new Error(`${what} is not available in the demo. View the source for the real implementation.`));
}

export const demoScanProvider = {
  mode: "demo",

  // The demo deliberately exposes only the read-only product experience.
  // Panels consult these flags instead of testing for demo mode themselves.
  capabilities: {
    liveScan: false,
    history: true,
    accountsAdmin: false,
    team: false,
    billing: false,
    cleanupExecute: false,
  },

  // --- Scans ---
  async runScan() {
    await delay(SIMULATED_SCAN_MS);
    return {
      ...currentScan,
      alerts: alertsFixture.alerts,
      persisted: false,
    };
  },

  async listScans() {
    return {
      scans: SCANS.map((scan, i) => {
        const older = SCANS[i + 1];
        return {
          scan_id: scan.scan_id,
          created_at: scan.created_at,
          resource_count: scan.resources.length,
          summary: scan.summary,
          vs_previous: older ? diff(older, scan).summary : null,
        };
      }),
    };
  },

  async getScan(scanId) {
    const scan = SCANS.find((s) => s.scan_id === scanId);
    if (!scan) throw new Error(`Unknown demo scan: ${scanId}`);
    return scan;
  },

  async compareScans(fromId, toId) {
    const from = SCANS.find((s) => s.scan_id === fromId);
    const to = SCANS.find((s) => s.scan_id === toId);
    if (!from || !to) throw new Error("Unknown demo scan id");
    return diff(from, to);
  },

  // --- Accounts (read-only in the demo) ---
  async listAccounts() {
    return accountsFixture;
  },
  createAccount: notAvailable("Registering an AWS account"),
  deleteAccount: notAvailable("Removing an AWS account"),

  // --- Team / billing: hidden in the demo via capabilities ---
  async getMe() {
    return { tenant_id: "demo", user_id: "demo", role: "viewer", name: "Demo visitor" };
  },
  listUsers: notAvailable("Team management"),
  createUser: notAvailable("Adding a team member"),
  deleteUser: notAvailable("Removing a team member"),
  getBilling: notAvailable("Billing"),
  setPlan: notAvailable("Changing plan"),
  startCheckout: notAvailable("Checkout"),

  // --- Cleanup: catalog is shown so visitors can read the safety model,
  // but execution is impossible — there is no account to act on. ---
  async getCleanupActions() {
    return {
      enabled: false,
      actions: [
        {
          key: "stop_ec2_instance",
          resource_type: "EC2 Instance",
          verb: "Stop",
          destructive: false,
          reversible: true,
          description: "Stop a running instance to halt compute charges.",
        },
        {
          key: "release_elastic_ip",
          resource_type: "Elastic IP",
          verb: "Release",
          destructive: true,
          reversible: false,
          description: "Release an unassociated Elastic IP to stop hourly charges.",
        },
        {
          key: "delete_unattached_ebs_volume",
          resource_type: "EBS Volume",
          verb: "Delete",
          destructive: true,
          reversible: false,
          description: "Delete an unattached (available) volume. The data cannot be recovered.",
        },
      ],
      not_supported: [
        { resource_type: "NAT Gateway", reason: "Deleting one can break outbound connectivity for a whole subnet." },
        { resource_type: "EC2 Instance", reason: "Termination is irreversible; only stopping is automated." },
        { resource_type: "S3 Bucket", reason: "Bucket contents cannot be safely judged from metadata alone." },
        { resource_type: "RDS Database", reason: "Deletion risks data loss even with automated snapshots." },
      ],
    };
  },
  async getCleanupAudit() {
    return { entries: [] };
  },
  executeCleanup: notAvailable("Cleanup execution"),
};
