/**
 * What the Min. $/mo tile is compared with depends on what Dashboard tells it
 * about the scan on screen — live or saved, persisted or not, complete or not.
 * ExposureCard's own tests cover the rule; these cover the wiring.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const runScan = vi.fn();
const getScan = vi.fn();

vi.mock("../data/scanProvider.js", () => ({
  isDemoMode: true,
  capabilities: {
    liveScan: false, // scans itself on load, like the demo
    team: false,
    accountsAdmin: false,
    cleanupPreview: false,
    cleanupExecute: false,
  },
  scanProvider: {
    capabilities: { cleanupPreview: false, cleanupExecute: false },
    getMe: async () => ({ user_id: "u1", role: "member" }),
    listScans: async () => ({ scans: listed }),
    listAccounts: async () => ({ accounts: [] }),
    listUsers: async () => ({ users: [] }),
    runScan: (...a) => runScan(...a),
    getScan: (...a) => getScan(...a),
    getCleanupActions: async () => ({ enabled: false, actions: [], not_supported: [] }),
    getCleanupAudit: async () => ({ entries: [] }),
  },
}));

import Dashboard from "./Dashboard.jsx";

const summaryOf = (cost) => ({
  total_resources: 1,
  by_risk_level: { HIGH: 1 },
  estimated_monthly_cost: cost,
});

// Noon UTC, so "Aug 14" reads the same in any US timezone.
const AUG_14 = {
  scan_id: "2026-08-14T12:00:00.000Z_aaaa1111",
  created_at: "2026-08-14T12:00:00.000Z",
  resource_count: 1,
  summary: summaryOf(91.8),
  complete: true,
  vs_previous: null,
  previous: null,
};
const AUG_17 = {
  scan_id: "2026-08-17T12:00:00.000Z_bbbb2222",
  created_at: "2026-08-17T12:00:00.000Z",
  resource_count: 1,
  summary: summaryOf(123.3),
  complete: true,
  vs_previous: { added: 0, removed: 0, changed: 0, unchanged: 1 },
  previous: {
    scan_id: AUG_14.scan_id,
    created_at: AUG_14.created_at,
    summary: AUG_14.summary,
    complete: true,
  },
};
const SCANS = [AUG_17, AUG_14];
let listed = SCANS;

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
    account_id: null,
    account_label: null,
    created_at: null,
    details: null,
    estimated_monthly_cost: 3.65,
    cost_currency: "USD",
    cost_source: "static",
  },
];

// The demo's live scan: unsaved, timed by its newest fixture, and complete.
const LIVE = {
  scan_id: null,
  as_of: AUG_17.created_at,
  summary: AUG_17.summary,
  resources: RESOURCES,
  alerts: [],
  persisted: false,
  regions_failed: [],
  scanners_failed: [],
  complete: true,
};

const hook = (name) => document.querySelectorAll(`[data-scene="${name}"]`);

beforeEach(() => {
  vi.clearAllMocks();
  listed = SCANS;
  runScan.mockResolvedValue(LIVE);
});

describe("Dashboard Min. $/mo tile", () => {
  it("compares the live scan with the saved scan before it", async () => {
    render(<Dashboard />);

    await waitFor(() => expect(screen.getByText(/vs Aug 14 scan/)).toBeInTheDocument());
    expect(screen.getByText(/vs Aug 14 scan/).closest("p")).toHaveTextContent(
      "+$31.50 vs Aug 14 scan"
    );
  });

  it("compares a loaded saved scan with the scan saved before it, and the first with nothing", async () => {
    const user = userEvent.setup();
    getScan.mockResolvedValue({ ...AUG_14, resources: RESOURCES });
    render(<Dashboard />);
    await waitFor(() => expect(hook("history-item")).toHaveLength(2));

    await user.click(hook("history-item")[1]); // the Aug 14 scan, the oldest

    await waitFor(() => expect(hook("saved-scan-banner")).toHaveLength(1));
    expect(screen.getByText("$91.80")).toBeInTheDocument();
    expect(screen.queryByText(/vs Aug \d+ scan/)).not.toBeInTheDocument();
  });

  it("does not compare a live scan that could not read everything", async () => {
    runScan.mockResolvedValue({
      ...LIVE,
      regions_failed: [
        { region: "us-west-2", reason: "AccessDenied", account_id: null, account_label: null },
      ],
      complete: false,
    });
    render(<Dashboard />);

    await waitFor(() =>
      expect(screen.getByText("Not compared: this scan is incomplete")).toBeInTheDocument()
    );
    expect(screen.queryByText(/vs Aug 14 scan/)).not.toBeInTheDocument();
  });

  it("does not compare a saved scan that could not read everything, reopened from history", async () => {
    // The live result said it was incomplete; its saved copy says so too, so
    // reopening it cannot turn the region it missed into a fall.
    const user = userEvent.setup();
    const incomplete = { ...AUG_17, complete: false };
    listed = [incomplete, AUG_14];
    getScan.mockResolvedValue({ ...incomplete, resources: RESOURCES });
    render(<Dashboard />);
    await waitFor(() => expect(hook("history-item")).toHaveLength(2));

    await user.click(hook("history-item")[0]);

    await waitFor(() => expect(hook("saved-scan-banner")).toHaveLength(1));
    expect(screen.getByText("Not compared: this scan is incomplete")).toBeInTheDocument();
  });
});
