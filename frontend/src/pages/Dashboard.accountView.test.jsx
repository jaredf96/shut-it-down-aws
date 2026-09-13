/**
 * The account view must not outlive the findings it was chosen from.
 *
 * Dashboard narrows the findings table to one account with a select it offers
 * only when the findings span two or more. The choice used to survive whatever
 * replaced them — a rescan, a saved scan — so once its account was gone the
 * table reported no findings under summary tiles still counting them, beside a
 * select that showed "All accounts" or was not rendered at all. Neither could
 * undo it.
 *
 * Nor may it mistake one account for another. A name is only what an account
 * was registered under: two accounts can share one, an account registered later
 * can take the name of one removed, and one can even be called "all".
 *
 * And when loads overlap, the page must end on the one asked for last. The
 * history stays clickable while a scan is in flight, so an overtaken load used
 * to land anyway: the page ended on whichever response arrived last, and one
 * without the chosen account cleared the choice on its way through. The history
 * list races the same way, since every scan that lands refreshes it.
 */
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const runScan = vi.fn();
const getScan = vi.fn();
const listScans = vi.fn();

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
    listScans: (...a) => listScans(...a),
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

// Newest first, as the history lists them.
const SCANS = [
  {
    scan_id: "2026-08-14T04:12:44Z_efgh5678",
    created_at: "2026-08-14T04:12:44Z",
    resource_count: 2,
    summary: { by_risk_level: { HIGH: 2 } },
    vs_previous: null,
  },
  {
    scan_id: "2026-08-13T16:41:09Z_abcd1234",
    created_at: "2026-08-13T16:41:09Z",
    resource_count: 3,
    summary: { by_risk_level: { HIGH: 3 } },
    vs_previous: null,
  },
];

// Accounts a test names itself, because ACCOUNT_IDS gives a name one account
// and nothing keeps a name to one.
const ID_A = "777788889999";
const ID_B = "123456789012";

/**
 * A scan result with findings in each named account: `accounts[label]` is a
 * count of findings in that label's account from ACCOUNT_IDS, or a list holding
 * each finding's own account ID.
 */
function scanOf(accounts) {
  const resources = Object.entries(accounts).flatMap(([label, findings]) => {
    const ids = Array.isArray(findings) ? findings : Array(findings).fill(ACCOUNT_IDS[label]);
    return ids.map((accountId, i) => ({
      resource_type: "Elastic IP",
      resource_id: `eipalloc-${label}-${i + 1}`,
      name: null,
      region: "us-east-1",
      status: "unassociated",
      risk_level: "HIGH",
      monthly_cost_risk: "AWS charges hourly for every public IPv4 address.",
      suggested_action: "Release it.",
      account_id: accountId,
      account_label: label,
      created_at: "2026-06-01T00:00:00Z",
      details: null,
      estimated_monthly_cost: 3.65,
      cost_currency: "USD",
      cost_source: "static",
    }));
  });
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
  listScans.mockReset();
  listScans.mockResolvedValue({ scans: SCANS });
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
    await waitFor(() => expect(hook("history-item")).toHaveLength(SCANS.length));
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

  it("does not carry the choice over to another account of the same name", async () => {
    // A name is only what an account was registered under. Remove one and
    // register another under its name, and the choice still names the account
    // that left, not the one that arrived.
    const user = userEvent.setup();
    await renderScanned(scanOf({ student: [ID_A], "sandbox-lab": 1 }));
    await user.selectOptions(accountView(), "student");
    expect(findingRows()).toHaveLength(1);

    await rescan(user, scanOf({ student: [ID_B], "sandbox-lab": 1 }));

    expect(accountView()).toHaveValue("all");
    expect(findingRows()).toHaveLength(2);
  });

  it("keeps a choice the new scan still offers", async () => {
    const user = userEvent.setup();
    await renderScanned(scanOf(TWO_ACCOUNTS));
    await user.selectOptions(accountView(), "training-account");

    await rescan(user, scanOf({ "sandbox-lab": 1, "training-account": 2 }));

    expect(accountView()).toHaveDisplayValue("training-account");
    expect(findingRows()).toHaveLength(2);
  });
});

describe("accounts the view tells apart", () => {
  it("offers two accounts that share a name as two choices", async () => {
    const user = userEvent.setup();
    await renderScanned(scanOf({ student: [ID_A, ID_B], "sandbox-lab": 1 }));

    // "All accounts" and each account once, and no two of them read the same.
    const names = within(accountView()).getAllByRole("option").map((o) => o.textContent);
    expect(new Set(names).size).toBe(4);

    const shown = new Set();
    for (const option of within(accountView()).getAllByRole("option", { name: /student/ })) {
      await user.selectOptions(accountView(), option);
      expect(findingRows()).toHaveLength(1);
      shown.add(findingRows()[0].textContent);
    }
    expect(shown.size).toBe(2);
  });

  it("narrows the table to an account named all", async () => {
    const user = userEvent.setup();
    await renderScanned(scanOf({ all: [ID_A], "sandbox-lab": 2 }));

    await user.selectOptions(accountView(), screen.getByRole("option", { name: "all" }));

    expect(findingRows()).toHaveLength(1);
  });
});

describe("overlapping loads", () => {
  // Two saved scans clicked one after the other, before either has landed. The
  // first lacks the chosen account; the second, where the page should end up,
  // offers it. Under the choice their row counts differ, so either on screen is
  // recognizable: three rows for the first, two for the second.
  const [second, first] = SCANS;
  const FIRST = scanOf({ "sandbox-lab": 3 });
  const SECOND = scanOf({ "sandbox-lab": 1, "training-account": 2 });

  /** A promise the test settles by hand. */
  function deferred() {
    let resolve, reject;
    const promise = new Promise((res, rej) => {
      resolve = res;
      reject = rej;
    });
    return { promise, resolve, reject };
  }

  /** Hold every saved-scan request open; the returned `land` answers one. */
  function holdSavedScans() {
    const pending = new Map();
    getScan.mockImplementation((scanId) => new Promise((resolve) => pending.set(scanId, resolve)));
    return (scan, { resources, summary }) =>
      act(async () => {
        pending.get(scan.scan_id)({ resources, summary, created_at: scan.created_at });
      });
  }

  /** Choose an account, then click the first saved scan and then the second. */
  async function chooseThenClickBoth(user) {
    await renderScanned(scanOf(TWO_ACCOUNTS));
    await user.selectOptions(accountView(), "training-account");
    await waitFor(() => expect(hook("history-item")).toHaveLength(SCANS.length));
    const land = holdSavedScans();
    await user.click(hook("history-item")[SCANS.indexOf(first)]);
    await user.click(hook("history-item")[SCANS.indexOf(second)]);
    return land;
  }

  it("opens the second on the chosen account when the first lands before it", async () => {
    const user = userEvent.setup();
    const land = await chooseThenClickBoth(user);

    await land(first, FIRST);
    await land(second, SECOND);

    expect(accountView()).toHaveDisplayValue("training-account");
    expect(findingRows()).toHaveLength(2);
  });

  it("keeps the second on screen when the first lands after it", async () => {
    const user = userEvent.setup();
    const land = await chooseThenClickBoth(user);

    await land(second, SECOND);
    await land(first, FIRST);

    expect(findingRows()).toHaveLength(2);
    expect(accountView()).toHaveDisplayValue("training-account");
  });

  it("stays loading until the second has landed", async () => {
    // The scan button reports `loading`, and automation waits for it to go idle.
    const user = userEvent.setup();
    const land = await chooseThenClickBoth(user);
    const state = () => hook("scan-button")[0].dataset.sceneState;

    await land(first, FIRST);
    expect(state()).toBe("scanning");

    await land(second, SECOND);
    expect(state()).toBe("idle");
  });

  it("keeps a saved scan clicked during a live scan when the live scan lands", async () => {
    const user = userEvent.setup();
    await renderScanned(scanOf(TWO_ACCOUNTS));
    await waitFor(() => expect(hook("history-item")).toHaveLength(SCANS.length));
    const live = deferred();
    runScan.mockReturnValueOnce(live.promise);
    await user.click(hook("scan-button")[0]);
    const land = holdSavedScans();
    await user.click(hook("history-item")[SCANS.indexOf(second)]);

    await land(second, SECOND);
    await act(async () => live.resolve(scanOf({ "sandbox-lab": 1 })));

    expect(hook("saved-scan-banner")).toHaveLength(1);
    expect(findingRows()).toHaveLength(3);
    // The abandoned scan's progress bar went with it, not on under the saved scan.
    expect(hook("scan-progress")).toHaveLength(0);
  });

  it.each([
    ["answers with less", (refresh) => refresh.resolve({ scans: SCANS })],
    ["fails", (refresh) => refresh.reject(new Error("The API is unreachable."))],
  ])("keeps the newer history when an older refresh %s after it", async (_, settle) => {
    // Two live scans overlap, "Live" starting the second while the first is in
    // flight, and each refreshes the history as it lands. The first scan's
    // refresh goes out first and sees less, but answers last.
    const user = userEvent.setup();
    await renderScanned(scanOf(TWO_ACCOUNTS));
    await waitFor(() => expect(hook("history-item")).toHaveLength(SCANS.length));
    const [olderScan, newerScan] = [deferred(), deferred()];
    runScan.mockReturnValueOnce(olderScan.promise).mockReturnValueOnce(newerScan.promise);
    await user.click(hook("scan-button")[0]);
    await user.click(screen.getByRole("button", { name: "Live" }));

    const [olderRefresh, newerRefresh] = [deferred(), deferred()];
    listScans.mockReturnValueOnce(olderRefresh.promise).mockReturnValueOnce(newerRefresh.promise);
    await act(async () => olderScan.resolve(scanOf(TWO_ACCOUNTS)));
    await act(async () => newerScan.resolve(scanOf(TWO_ACCOUNTS)));
    const saved = { ...SCANS[0], scan_id: "2026-08-15T09:30:02Z_ijkl9012" };
    await act(async () => newerRefresh.resolve({ scans: [saved, ...SCANS] }));
    await act(async () => settle(olderRefresh));

    expect(hook("history-item")).toHaveLength(SCANS.length + 1);
  });
});
