/**
 * The account view must not outlive the findings it was chosen from.
 *
 * Dashboard narrows the findings table to one account with a select it offers
 * only when the findings span two or more. The choice used to survive whatever
 * replaced them — a rescan, a saved scan — so once its account was gone the
 * table reported no findings under summary tiles still counting them, beside a
 * select that showed "All accounts" or was not rendered at all. Neither could
 * undo it.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const runScan = vi.fn();
const getScan = vi.fn();

vi.mock("../data/scanProvider.js", () => ({
  isDemoMode: true,
  capabilities: {
    liveScan: false, // scans on load, as the demo does
    team: false,
    accountsAdmin: false,
    cleanupPreview: false,
    cleanupExecute: false,
  },
  scanProvider: {
    getMe: async () => ({ user_id: "u1", role: "member" }),
    listScans: async () => ({ scans: SCANS }),
    listAccounts: async () => ({ accounts: [] }),
    runScan: (...a) => runScan(...a),
    getScan: (...a) => getScan(...a),
    getCleanupActions: async () => ({ enabled: false, actions: [], not_supported: [] }),
    getCleanupAudit: async () => ({ entries: [] }),
  },
}));

import Dashboard from "./Dashboard.jsx";

const ACCOUNT_IDS = {
  "sandbox-lab": "111122223333",
  "training-account": "444455556666",
  "student-03": "222222222222",
};

const SCANS = [
  {
    scan_id: "2026-08-14T04:12:44Z_efgh5678",
    created_at: "2026-08-14T04:12:44Z",
    resource_count: 2,
    summary: { by_risk_level: { HIGH: 2 } },
    vs_previous: null,
  },
];

/** A scan result holding `counts[label]` findings in each named account. */
function scanOf(counts) {
  const resources = Object.entries(counts).flatMap(([label, count]) =>
    Array.from({ length: count }, (_, i) => ({
      resource_type: "Elastic IP",
      resource_id: `eipalloc-${label}-${i + 1}`,
      name: null,
      region: "us-east-1",
      status: "unassociated",
      risk_level: "HIGH",
      monthly_cost_risk: "AWS charges hourly for every public IPv4 address.",
      suggested_action: "Release it.",
      account_id: ACCOUNT_IDS[label],
      account_label: label,
      created_at: "2026-06-01T00:00:00Z",
      details: null,
      estimated_monthly_cost: 3.65,
      cost_currency: "USD",
      cost_source: "static",
    }))
  );
  return {
    resources,
    summary: {
      total_resources: resources.length,
      estimated_monthly_cost: 3.65 * resources.length,
      by_risk_level: { HIGH: resources.length, REVIEW: 0, MEDIUM: 0, LOW: 0 },
    },
    alerts: [],
    regions_failed: [],
    scanners_failed: [],
    as_of: "2026-08-17T10:05:11Z",
  };
}

const TWO_ACCOUNTS = { "sandbox-lab": 2, "training-account": 1 };

const hook = (name) => document.querySelectorAll(`[data-scene="${name}"]`);
const findingRows = () => hook("findings-row");
const accountView = () => screen.queryByRole("combobox", { name: /account view/i });

/** Render the page and wait for the scan it runs on load. */
async function renderScanned(result) {
  runScan.mockResolvedValueOnce(result);
  render(<Dashboard />);
  await waitFor(() => expect(findingRows()).toHaveLength(result.resources.length));
}

/**
 * Run a scan from the header button and wait for it to land. The button reads
 * "scanning" from the click until the result renders, so "idle" after a click
 * means the new findings are on screen.
 */
async function rescan(user, result) {
  runScan.mockResolvedValueOnce(result);
  await user.click(hook("scan-button")[0]);
  await waitFor(() => expect(hook("scan-button")[0].dataset.sceneState).toBe("idle"));
}

beforeEach(() => {
  runScan.mockReset();
  getScan.mockReset();
});

describe("the account view across scans", () => {
  it("shows every finding when a rescan no longer covers the chosen account", async () => {
    // An account was removed, so the rescan covers one — and the select is not
    // rendered, since a single account offers no choice.
    const user = userEvent.setup();
    await renderScanned(scanOf(TWO_ACCOUNTS));
    await user.selectOptions(accountView(), "training-account");
    expect(findingRows()).toHaveLength(1);

    await rescan(user, scanOf({ "sandbox-lab": 2 }));

    expect(findingRows()).toHaveLength(2);
    expect(accountView()).not.toBeInTheDocument();
  });

  it("shows every finding when the chosen account drops out but two remain", async () => {
    // The select stays up but holds no option for the choice, so it displays
    // its first, "All accounts". Picking that again would not clear the choice:
    // an option already selected fires no change.
    const user = userEvent.setup();
    await renderScanned(scanOf({ "sandbox-lab": 1, "training-account": 1, "student-03": 1 }));
    await user.selectOptions(accountView(), "student-03");

    await rescan(user, scanOf({ "sandbox-lab": 1, "training-account": 1 }));

    expect(findingRows()).toHaveLength(2);
    expect(accountView()).toHaveValue("all");
  });

  it("shows every finding when a saved scan does not cover the chosen account", async () => {
    const user = userEvent.setup();
    await renderScanned(scanOf(TWO_ACCOUNTS));
    await user.selectOptions(accountView(), "training-account");

    const { resources, summary } = scanOf({ "sandbox-lab": 2 });
    getScan.mockResolvedValueOnce({ resources, summary, created_at: SCANS[0].created_at });
    await waitFor(() => expect(hook("history-item")).toHaveLength(1));
    await user.click(hook("history-item")[0]);
    await waitFor(() => expect(hook("saved-scan-banner")).toHaveLength(1));

    expect(findingRows()).toHaveLength(2);
    expect(accountView()).not.toBeInTheDocument();
  });

  it.each([
    ["another account", { "sandbox-lab": 2 }],
    ["the chosen account alone", { "training-account": 1 }],
  ])("does not restore the choice after a scan of %s", async (_, between) => {
    // A choice merely overridden while the select could not offer it would still
    // be stored, and would narrow the table again, unasked, once both accounts
    // were back.
    const user = userEvent.setup();
    await renderScanned(scanOf(TWO_ACCOUNTS));
    await user.selectOptions(accountView(), "training-account");
    await rescan(user, scanOf(between));

    await rescan(user, scanOf(TWO_ACCOUNTS));

    expect(accountView()).toHaveValue("all");
    expect(findingRows()).toHaveLength(3);
  });

  it("keeps a choice the new scan still offers", async () => {
    const user = userEvent.setup();
    await renderScanned(scanOf(TWO_ACCOUNTS));
    await user.selectOptions(accountView(), "training-account");

    await rescan(user, scanOf({ "sandbox-lab": 1, "training-account": 2 }));

    expect(accountView()).toHaveValue("training-account");
    expect(findingRows()).toHaveLength(2);
  });
});
