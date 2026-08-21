/**
 * The age column, mostly.
 *
 * Age is measured against the scan rather than against now, so a saved scan
 * reads the same tomorrow as it did the day it ran — and so the demo's pinned
 * fixture ages do not creep upward past the committed screenshots.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ResourceTable from "./ResourceTable.jsx";

const SCANNED_AT = "2026-08-17T14:05:11.884Z";

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
  created_at: "2026-05-22T14:05:11.884Z", // 87 days before the scan
  details: null,
  estimated_monthly_cost: 7.59,
  cost_currency: "USD",
  cost_source: "static",
  ...over,
});

const ageCell = () => within(screen.getAllByRole("row")[1]).getByTitle(/created|does not report|unreadable/i);

describe("ResourceTable age column", () => {
  it("measures age against the scan, not against today", () => {
    render(<ResourceTable resources={[resource()]} asOf={SCANNED_AT} />);
    expect(ageCell()).toHaveTextContent("87d");
  });

  it("falls back to now when the scan carries no timestamp", () => {
    const twoDaysAgo = new Date(Date.now() - 2 * 86_400_000).toISOString();
    render(<ResourceTable resources={[resource({ created_at: twoDaysAgo })]} />);
    expect(ageCell()).toHaveTextContent("2d");
  });

  it("shows a dash when the API reports no creation time", () => {
    render(<ResourceTable resources={[resource({ created_at: null })]} asOf={SCANNED_AT} />);

    const cell = ageCell();
    expect(cell).toHaveTextContent("—");
    expect(cell).toHaveAttribute("title", expect.stringMatching(/does not report a creation time/i));
  });

  it("does not render a negative age for a resource newer than the scan", () => {
    render(
      <ResourceTable
        resources={[resource({ created_at: "2026-09-01T00:00:00.000Z" })]}
        asOf={SCANNED_AT}
      />
    );
    expect(ageCell()).toHaveTextContent("<1d");
  });

  it("rounds down rather than showing a fraction of a day", () => {
    render(
      <ResourceTable
        resources={[resource({ created_at: "2026-08-17T02:00:00.000Z" })]}
        asOf={SCANNED_AT}
      />
    );
    expect(ageCell()).toHaveTextContent("<1d");
  });

  it("keeps the header aligned with the row", () => {
    render(<ResourceTable resources={[resource()]} asOf={SCANNED_AT} />);

    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toContain("Age");
    expect(headers.indexOf("Age")).toBe(headers.indexOf("Status") + 1);
  });
});
