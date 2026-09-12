/**
 * The `data-scene` attributes are an automation contract, not decoration.
 *
 * Three Playwright scripts outside this repository drive the real dashboard to
 * record the walkthrough video. They used to wait on styling classes
 * (`.table-wrapper`, `.cleanup__flag.is-on`, `form.accounts__form`) and on copy
 * (`getByPlaceholder(/^Display name/)`), which meant any restyle or reword
 * silently broke a recording session that costs real money to stand up — a
 * cross-account AWS lab with billable fixtures, torn down the same sitting.
 *
 * So the scripts now wait on `data-scene` instead, and this file is what stops
 * that from rotting. Every hook below is one a scene script locates. Deleting
 * or renaming one fails here, at `npm test`, rather than at 2am with the lab
 * running.
 *
 * Adding a hook: add it here in the same commit. A contract nothing checks is
 * the failure this project forbids by name.
 *
 * The BEM classes are deliberately left in place alongside these attributes.
 * They still do the styling; they are simply no longer load-bearing for
 * automation.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const runScan = vi.fn();
const getScan = vi.fn();

vi.mock("./data/scanProvider.js", () => ({
  isDemoMode: true,
  capabilities: {
    liveScan: false, // the demo scans itself on load
    team: false,
    accountsAdmin: false,
    cleanupPreview: true,
    cleanupExecute: false,
  },
  scanProvider: {
    capabilities: { cleanupPreview: true, cleanupExecute: false },
    getMe: async () => ({ user_id: "u1", role: "admin" }),
    listScans: async () => ({ scans: SCANS }),
    listAccounts: async () => ({ accounts: ACCOUNTS }),
    listUsers: async () => ({ users: [] }),
    runScan: (...a) => runScan(...a),
    getScan: (...a) => getScan(...a),
    getCleanupActions: async () => ({
      enabled: true,
      actions: [
        {
          key: "release_elastic_ip",
          resource_type: "Elastic IP",
          verb: "Release",
          destructive: false,
          reversible: true,
          description: "Release an unassociated Elastic IP.",
        },
      ],
      not_supported: [],
    }),
    getCleanupAudit: async () => ({
      entries: [
        {
          id: "a1",
          status: "error",
          action: "release_elastic_ip",
          resource_id: "eipalloc-1",
          account_id: "111122223333",
          dry_run: false,
          created_at: "2026-08-17T10:05:11Z",
        },
      ],
    }),
    executeCleanup: async () => ({ status: "refused", detail: "nope" }),
  },
}));

import AccountsPanel from "./components/AccountsPanel.jsx";
import CleanupPanel from "./components/CleanupPanel.jsx";
import ResourceTable from "./components/ResourceTable.jsx";
import ScanHistory from "./components/ScanHistory.jsx";
import ScanProgress from "./components/ScanProgress.jsx";
import Dashboard from "./pages/Dashboard.jsx";

const ACCOUNTS = [
  {
    account_id: "111122223333",
    name: "sandbox-lab",
    role_arn: "arn:aws:iam::111122223333:role/ShutItDownScannerRole",
  },
];

const SCANS = [
  {
    scan_id: "2026-08-17T10:05:11Z_abcd1234",
    created_at: "2026-08-17T10:05:11Z",
    resource_count: 2,
    summary: { by_risk_level: { HIGH: 1 } },
    vs_previous: { added: 1, removed: 0, changed: 0 },
  },
  {
    scan_id: "2026-08-14T04:12:44Z_efgh5678",
    created_at: "2026-08-14T04:12:44Z",
    resource_count: 1,
    summary: { by_risk_level: { HIGH: 1 } },
    vs_previous: null,
  },
];

const RESOURCES = [
  {
    resource_type: "Elastic IP",
    resource_id: "eipalloc-1",
    name: "left-over-lab-ip",
    region: "us-east-1",
    status: "unassociated",
    risk_level: "HIGH",
    monthly_cost_risk: "AWS charges hourly for every public IPv4 address.",
    suggested_action: "Release it.",
    account_id: "111122223333",
    account_label: "sandbox-lab",
    created_at: "2026-06-01T00:00:00Z",
    details: null,
    estimated_monthly_cost: 3.65,
    cost_currency: "USD",
    cost_source: "static",
  },
];

const SCAN_RESULT = {
  resources: RESOURCES,
  summary: {
    total_resources: 1,
    estimated_monthly_cost: 3.65,
    by_risk_level: { HIGH: 1, REVIEW: 0, MEDIUM: 0, LOW: 0 },
  },
  alerts: [],
  regions_failed: [],
  scanners_failed: [],
  as_of: "2026-08-17T10:05:11Z",
};

const hook = (name) => document.querySelectorAll(`[data-scene="${name}"]`);

/** Assert a hook resolves to at least one element, naming the scene on failure. */
function expectHook(name, scene) {
  const found = hook(name);
  expect(
    found.length,
    `data-scene="${name}" resolved ${found.length} elements — ${scene} waits on it`
  ).toBeGreaterThan(0);
}

beforeEach(() => {
  vi.clearAllMocks();
  runScan.mockResolvedValue(SCAN_RESULT);
  getScan.mockResolvedValue({
    resources: RESOURCES,
    summary: SCAN_RESULT.summary,
    created_at: "2026-08-14T04:12:44Z",
  });
  // jsdom implements neither, and Dashboard calls both on a finished scan.
  window.matchMedia = window.matchMedia || ((q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} }));
  Element.prototype.scrollIntoView = vi.fn();
});

describe("scene 3 — register an account and scan", () => {
  it("exposes every hook the script waits on", async () => {
    const user = userEvent.setup();
    render(<AccountsPanel accounts={ACCOUNTS} isAdmin onAdd={vi.fn()} onDelete={vi.fn()} />);

    expectHook("accounts-panel", "scene 3");
    expectHook("accounts-arn", "scene 3");
    expectHook("accounts-add", "scene 3");

    await user.click(hook("accounts-add")[0]);

    for (const name of [
      "accounts-form",
      "accounts-name",
      "accounts-role-arn",
      "accounts-external-id",
      "accounts-submit",
    ]) {
      expectHook(name, "scene 3");
    }
  });

  it("exposes the registration error hook when the add fails", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn().mockRejectedValue(new Error("that role ARN is not readable"));
    render(<AccountsPanel accounts={[]} isAdmin onAdd={onAdd} onDelete={vi.fn()} />);

    await user.click(hook("accounts-add")[0]);
    await user.type(hook("accounts-name")[0], "444455556666");
    await user.type(hook("accounts-role-arn")[0], "arn:aws:iam::444455556666:role/R");
    await user.click(hook("accounts-submit")[0]);

    await waitFor(() => expectHook("accounts-error", "scene 3"));
  });

  it("exposes the findings table and its Account column", () => {
    render(<ResourceTable resources={RESOURCES} asOf="2026-08-17T10:05:11Z" />);
    expectHook("findings", "scenes 3, 5 and 6");
    expectHook("findings-account-header", "scene 3 — the ACCOUNT column is the proof");
  });

  it("exposes the in-flight scan indicator", () => {
    render(<ScanProgress done={false} onDone={vi.fn()} />);
    expectHook("scan-progress", "scene 3 waits for it to detach");
  });
});

describe("scene 5 — the cleanup refusal", () => {
  it("exposes the history sidebar the scene loads a saved scan from", () => {
    render(
      <ScanHistory
        scans={SCANS}
        activeId={null}
        onSelect={vi.fn()}
        onLive={vi.fn()}
        viewingLive
      />
    );
    expectHook("history-panel", "scene 5");
    expect(hook("history-item").length, "scene 5 clicks the newest saved scan").toBe(2);
  });

  it("exposes every gate hook, and the flag state as an attribute", async () => {
    render(<CleanupPanel isAdmin resources={RESOURCES} />);

    await waitFor(() => expectHook("cleanup-panel", "scene 5"));

    // The scene refuses to record unless the backend really has the flag on,
    // so the state has to be readable without matching a styling class.
    expect(hook("cleanup-flag")[0].dataset.sceneState).toBe("off"); // cleanupExecute: false

    for (const name of [
      "cleanup-form",
      "cleanup-action",
      "cleanup-resource-id",
      "cleanup-region",
      "cleanup-confirm",
      "cleanup-dry-run",
      "cleanup-submit",
    ]) {
      expectHook(name, "scene 5");
    }

    // Rendered only when the loaded scan holds a finding this action applies to.
    expectHook("cleanup-finding", "scene 5 picks the target from it");

    // The audit trail, and the refusal row the scene ends on.
    await waitFor(() => expectHook("cleanup-audit", "scene 5"));
    expect(
      hook("cleanup-audit-status")[0].dataset.sceneStatus,
      "scene 5 waits for a refused attempt to land in the trail"
    ).toBe("error");
  });

  it("exposes the target-account selector when the scan spans two accounts", async () => {
    // Rendered only when the scan saw more than one account — which is exactly
    // the cross-account case the walkthrough exists to prove, so the hook needs
    // pinning even though no scene locates it yet.
    const second = { ...RESOURCES[0], resource_id: "eipalloc-2", account_id: "444455556666", account_label: "training-account" };
    render(<CleanupPanel isAdmin resources={[...RESOURCES, second]} />);
    await waitFor(() => expectHook("cleanup-account", "cross-account cleanup"));
  });

  it("reports the submit button's mode, which is the dry-run gate", async () => {
    render(<CleanupPanel isAdmin resources={RESOURCES} />);
    await waitFor(() => expectHook("cleanup-submit", "scene 5"));

    // This build may only preview, so the checkbox is locked and the mode stays
    // dry. Scene 5 runs against a build where it can be unchecked.
    expect(hook("cleanup-submit")[0].dataset.sceneMode).toBe("dry");
    expect(hook("cleanup-dry-run")[0]).toBeDisabled();
  });

  it("exposes the result banner", async () => {
    const user = userEvent.setup();
    render(<CleanupPanel isAdmin resources={RESOURCES} />);
    await waitFor(() => expectHook("cleanup-form", "scene 5"));

    await user.selectOptions(hook("cleanup-finding")[0], "eipalloc-1");
    await user.type(hook("cleanup-confirm")[0], "eipalloc-1");
    await user.click(hook("cleanup-submit")[0]);

    await waitFor(() => expectHook("cleanup-result", "scene 5 reads the 502 sentence from it"));
  });
});

describe("scenes 3 and 6 — the page shell", () => {
  it("exposes the demo notice, scan button, caveat and findings", async () => {
    render(<Dashboard />);

    expectHook("demo-notice", "scene 6 — proof the build is fixtures");
    expectHook("scan-button", "scenes 3 and 6");

    // Scenes 3 and 6 used to read the button's label ("Scanning…" then "Run
    // scan") to know a scan had finished, which made a copy edit a recording
    // failure. The state is an attribute now.
    await waitFor(() => expect(hook("scan-button")[0].dataset.sceneState).toBe("idle"));

    await waitFor(() => expectHook("summary-caveat", "scenes 3 and 6 wait for it"));
    expectHook("findings", "scenes 3, 5 and 6");
  });

  it("exposes the saved-scan banner scene 5 waits for", async () => {
    const user = userEvent.setup();
    render(<Dashboard />);

    await waitFor(() => expect(hook("history-item").length).toBeGreaterThan(0));
    await user.click(hook("history-item")[0]);

    await waitFor(() => expectHook("saved-scan-banner", "scene 5"));
  });

  it("exposes the scan error banner", async () => {
    runScan.mockRejectedValue(new Error("the scan failed"));
    render(<Dashboard />);
    await waitFor(() => expectHook("scan-error", "scene 3 aborts the take on it"));
  });
});
