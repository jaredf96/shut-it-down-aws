/**
 * Which account a cleanup lands in.
 *
 * The panel used to build its request from resource_id, region and dry_run
 * alone. Every one of those is account-agnostic, so a resource sitting in a
 * registered account was cleaned with the server's *own* credentials — the
 * client-side half of the fallback the service already refuses. The live
 * precondition re-check usually failed it closed, because the id was not in the
 * host account; an id present in both accounts is where it bites.
 *
 * The service cannot infer the account from an id and a region, so the fix has
 * to be here: carry the account of the selected finding, and show it.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const executeCleanup = vi.fn();

vi.mock("../data/scanProvider.js", () => ({
  capabilities: { cleanupPreview: true, cleanupExecute: true },
  scanProvider: {
    getCleanupActions: async () => ({
      enabled: true,
      actions: [
        {
          key: "stop_ec2_instance",
          resource_type: "EC2 Instance",
          verb: "Stop",
          destructive: false,
          reversible: true,
          description: "Stop a running instance.",
        },
      ],
      not_supported: [],
    }),
    getCleanupAudit: async () => ({ entries: [] }),
    executeCleanup: (...args) => executeCleanup(...args),
  },
}));

import CleanupPanel from "./CleanupPanel.jsx";

const resource = (over = {}) => ({
  resource_type: "EC2 Instance",
  resource_id: "i-0abc",
  name: "tutorial-web-server",
  region: "us-east-1",
  status: "running",
  risk_level: "MEDIUM",
  monthly_cost_risk: "costs money",
  suggested_action: "stop it",
  account_id: null,
  account_label: null,
  created_at: null,
  details: null,
  estimated_monthly_cost: 7.59,
  cost_currency: "USD",
  cost_source: "static",
  ...over,
});

const SANDBOX = resource({
  resource_id: "i-sandbox",
  account_id: "111122223333",
  account_label: "sandbox-lab",
});
const TRAINING = resource({
  resource_id: "i-training",
  region: "us-west-2",
  account_id: "444455556666",
  account_label: "training-account",
});
const HOST = resource({ resource_id: "i-host" });

async function renderPanel(resources) {
  render(<CleanupPanel isAdmin resources={resources} />);
  // The catalog loads asynchronously; the panel renders null until it arrives.
  await screen.findByLabelText(/^Action$/i);
  return userEvent.setup();
}

/** Pick a finding, retype the id to confirm, submit. Returns the sent request. */
async function submit(user, findingId) {
  await user.selectOptions(screen.getByLabelText(/Eligible findings/i), findingId);
  await user.type(screen.getByLabelText(/^Type the resource ID again/i), findingId);
  await user.click(screen.getByRole("button", { name: /cleanup/i }));
  await waitFor(() => expect(executeCleanup).toHaveBeenCalled());
  return executeCleanup.mock.calls.at(-1)[0];
}

describe("CleanupPanel account targeting", () => {
  beforeEach(() => {
    executeCleanup.mockReset();
    executeCleanup.mockResolvedValue({ status: "dry_run", detail: "Would stop it." });
  });

  it("sends the account of the finding, so the service assumes that role", async () => {
    const user = await renderPanel([SANDBOX]);
    expect(await submit(user, "i-sandbox")).toMatchObject({
      resource_id: "i-sandbox",
      account_id: "111122223333",
    });
  });

  it("sends no account for a resource the host account owns", async () => {
    // Single-account mode still has to work: null means default credentials,
    // which is correct precisely when the resource is not in a registered one.
    const user = await renderPanel([HOST]);
    expect(await submit(user, "i-host")).toMatchObject({ account_id: null });
  });

  it("retargets when the operator picks a finding in another account", async () => {
    const user = await renderPanel([SANDBOX, TRAINING, HOST]);

    expect(await submit(user, "i-sandbox")).toMatchObject({ account_id: "111122223333" });
    expect(await submit(user, "i-training")).toMatchObject({ account_id: "444455556666" });
    expect(await submit(user, "i-host")).toMatchObject({ account_id: null });
  });

  it("shows which account the action will land in", async () => {
    const user = await renderPanel([SANDBOX, HOST]);

    await user.selectOptions(screen.getByLabelText(/Eligible findings/i), "i-sandbox");
    expect(screen.getByLabelText(/AWS account/i)).toHaveValue("111122223333");
    expect(screen.getByRole("option", { name: "sandbox-lab · 111122223333" })).toBeInTheDocument();
  });

  it("offers the host account only when the scan actually read it", async () => {
    // Offering "default credentials" in a purely multi-account deployment is
    // how a mis-set field becomes an action against the server's own account.
    await renderPanel([SANDBOX, TRAINING]);
    expect(screen.getByLabelText(/AWS account/i)).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Default credentials/i })).not.toBeInTheDocument();
  });

  it("hides the account field when there is only one place to act", async () => {
    await renderPanel([HOST]);
    expect(screen.queryByLabelText(/AWS account/i)).not.toBeInTheDocument();
  });
});
