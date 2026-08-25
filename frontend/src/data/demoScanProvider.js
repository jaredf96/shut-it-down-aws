// Provider backed by curated fixtures. Makes no network calls, holds no
// credentials, and cannot reach the private API — the public demo is a static
// deployment, so isolation is a property of the deployment, not of this flag.
//
// Fixtures live in repo-root `demo-data/` so the backend test suite can
// validate them against the real Pydantic models and they can never silently
// drift from the API schema.
import accountsRaw from "@demo-data/accounts.json";
import alertsRaw from "@demo-data/alerts.json";
import currentRaw from "@demo-data/current-scan.json";
import previousRaw from "@demo-data/previous-scan.json";

// JSON imports widen string literals ("HIGH" -> string), so assert the fixture
// types once, here, where untyped data enters typed code. The values are not
// taken on trust: backend/tests/test_demo_fixtures.py validates these same
// files against the real Pydantic models, which enforce the enums at runtime.
const currentScan = /** @type {import("./contract").Scan} */ (currentRaw);
const previousScan = /** @type {import("./contract").Scan} */ (previousRaw);
const alertsFixture = /** @type {{ alerts: import("./contract").Alert[] }} */ (alertsRaw);
const accountsFixture = /** @type {{ accounts: import("./contract").AwsAccount[] }} */ (
  accountsRaw
);

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

// Mirrors backend/app/services/cleanup_actions.py: the same three actions, the
// same preconditions, and the same wording, so the preview matches what the
// real service would say.
const CLEANUP_ACTIONS = {
  stop_ec2_instance: {
    resourceType: "EC2 Instance",
    requiredStatus: "running",
    wrongStatus: (s) => `Instance is '${s}', not 'running' — nothing to stop.`,
    wouldDo: (id) => `Would stop running instance ${id} (reversible).`,
  },
  release_elastic_ip: {
    resourceType: "Elastic IP",
    requiredStatus: "unassociated",
    wrongStatus: () => "Elastic IP is associated with a running resource — refusing to release.",
    wouldDo: (id) => `Would release unassociated Elastic IP ${id}.`,
  },
  delete_unattached_ebs_volume: {
    resourceType: "EBS Volume",
    requiredStatus: "available",
    wrongStatus: (s) =>
      `Volume is '${s}', not 'available' (unattached) — refusing to delete.`,
    wouldDo: (id) => `Would delete unattached volume ${id} (irreversible data loss).`,
  },
};

// Attempts accumulate in memory so the audit trail visibly fills as a visitor
// experiments — including the refusals, which is the point.
const demoAudit = [];

function notAvailable(what) {
  return () =>
    Promise.reject(new Error(`${what} is not available in the demo. View the source for the real implementation.`));
}

/** @type {import("./contract").ScanProvider} */
export const demoScanProvider = {
  mode: "demo",

  // The demo deliberately exposes only the read-only product experience.
  // Panels consult these flags instead of testing for demo mode themselves.
  capabilities: {
    liveScan: false,
    history: true,
    accountsAdmin: false,
    team: false,
    // The demo walks through the safety checks but can never mutate: there is
    // no account to act on and no credential to act with.
    cleanupPreview: true,
    cleanupExecute: false,
  },

  // --- Scans ---
  async runScan() {
    await delay(SIMULATED_SCAN_MS);
    // An unsaved live scan, field for field — not the saved fixture. Spreading
    // `currentScan` in here returned saved-scan metadata (`created_at`, a real
    // `scan_id`) that `GET /scan` never sends, so the demo was the more
    // generous of the two providers and the contract drifted to match it.
    return {
      // The demo persists nothing, and the live endpoint reports the same null
      // whenever a scan was not saved.
      scan_id: null,
      // The provider-normalized timestamp. The fixture's own `created_at` is
      // the honest answer for when this scan ran, and using it keeps the ages
      // in the table frozen at what the committed screenshots show. Stamping
      // now instead would creep every age upward by a day, every day.
      as_of: currentScan.created_at,
      summary: currentScan.summary,
      resources: currentScan.resources,
      alerts: alertsFixture.alerts,
      persisted: false,
      // The fixtures come from a moto sandbox that read every region it was
      // asked about, and every scanner ran, so there is genuinely nothing to
      // report here. Inventing a failure would be fabricating fixture data.
      regions_failed: [],
      scanners_failed: [],
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

  // --- Team: hidden in the demo via capabilities ---
  async getMe() {
    return { tenant_id: "demo", user_id: "demo", role: "viewer", name: "Demo visitor" };
  },
  listUsers: notAvailable("Team management"),
  createUser: notAvailable("Adding a team member"),
  deleteUser: notAvailable("Removing a team member"),

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
    return { entries: [...demoAudit].reverse() }; // newest first, like the API
  },

  /**
   * Walks the same gates the backend enforces, in the same order, against the
   * fixture resources — so the preview teaches the real safety model rather
   * than printing a canned string. Execution is impossible by construction:
   * there is no account to act on. See `cleanup_service.py`.
   */
  async executeCleanup(request) {
    await delay(400); // enough to read as work, not enough to feel broken
    const {
      action,
      resource_id,
      confirm_resource_id,
      region,
      account_id = null,
      dry_run = true,
    } = request;

    const record = (status, detail) => {
      const entry = {
        action,
        resource_id,
        region,
        account_id,
        dry_run: dry_run !== false,
        user_id: "demo",
        status,
        detail,
        created_at: new Date().toISOString(),
        id: `${new Date().toISOString()}_${Math.random().toString(16).slice(2, 10)}`,
      };
      demoAudit.push(entry); // every attempt is audited, including refusals
      return entry;
    };

    // Catalog check: the action must be one the service supports (checked
    // before confirmation, matching the backend's order).
    const spec = CLEANUP_ACTIONS[action];
    if (!spec) {
      throw new Error(record("unsupported_action", `Unsupported cleanup action: ${action}.`).detail);
    }

    // Typed confirmation: must match the resource id exactly.
    if (!resource_id || resource_id !== confirm_resource_id) {
      throw new Error(
        record("confirmation_mismatch", "Confirmation does not match the resource id.").detail
      );
    }

    // Live precondition re-check. The client is never trusted, so the
    // resource is looked up and its current state verified.
    //
    // The lookup is scoped by region *and* account, because the real service is:
    // it resolves credentials from the named account and calls Describe* against
    // that specific regional endpoint, so an id that exists in us-east-1 is
    // simply absent from us-west-2, and an id in one account is absent from
    // another. Ignoring either made the demo *laxer* than the service it is
    // supposed to be demonstrating.
    const found = currentScan.resources.find(
      (r) =>
        r.resource_id === resource_id &&
        r.resource_type === spec.resourceType &&
        r.region === region &&
        (r.account_id ?? null) === account_id
    );
    if (!found) {
      throw new Error(
        record(
          "precondition_failed",
          `${spec.resourceType} ${resource_id} not found in ${region}` +
            `${account_id ? ` for account ${account_id}` : ""}.`
        ).detail
      );
    }
    if (found.status !== spec.requiredStatus) {
      throw new Error(record("precondition_failed", spec.wrongStatus(found.status)).detail);
    }

    // Execution boundary: mutating requires a credential this build does not
    // have.
    if (dry_run === false) {
      throw new Error(
        record(
          "error",
          "Execution is unavailable in the demo: this build holds no AWS credentials " +
            "and targets no account. In a real deployment the scanner role is read-only, " +
            "so cleanup requires a separate, narrowly scoped role."
        ).detail
      );
    }

    return record("dry_run", spec.wouldDo(resource_id));
  },
};
