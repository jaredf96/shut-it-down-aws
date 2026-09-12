/**
 * The age column, mostly.
 *
 * Age is measured against the scan rather than against now, so a saved scan
 * reads the same tomorrow as it did the day it ran — and so the demo's pinned
 * fixture ages do not creep upward past the committed screenshots.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

describe("ResourceTable cost column", () => {
  it("labels the figure as a minimum, not an estimate", () => {
    render(<ResourceTable resources={[resource()]} asOf={SCANNED_AT} />);

    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent.trim());
    expect(headers).toContain("Min. $/mo");
    expect(headers).not.toContain("Est. $/mo");
  });

  it("says in the tooltip that the real cost is higher", () => {
    render(<ResourceTable resources={[resource()]} asOf={SCANNED_AT} />);

    // Scoped to the row: the selected finding's cost is also in the inspector,
    // so an unscoped query now matches twice.
    const cell = within(screen.getAllByRole("row")[1]).getByText("$7.59");
    expect(cell).toHaveAttribute("title", expect.stringMatching(/^At least \$7\.59\/month/));
    expect(cell).toHaveAttribute("title", expect.stringMatching(/real cost is higher/i));
  });

  it("distinguishes unpriced from free", () => {
    render(
      <ResourceTable
        resources={[resource({ estimated_monthly_cost: null, cost_source: "unknown" })]}
        asOf={SCANNED_AT}
      />
    );

    const cell = within(screen.getAllByRole("row")[1]).getByTitle(/not priced/i);
    expect(cell).toHaveTextContent("—");
    expect(cell).not.toHaveTextContent("$0");
  });
});

/**
 * Master/detail. The two prose fields were columns until they made every row
 * ~121px tall and the table 1874px — taller than any screen. They belong to the
 * selected row now, beside the table rather than inside it.
 */
describe("ResourceTable master/detail", () => {
  const eip = resource({
    resource_type: "Elastic IP",
    resource_id: "eipalloc-1",
    name: "left-over-lab-ip",
    risk_level: "HIGH",
    monthly_cost_risk: "AWS charges hourly for every public IPv4 address.",
    suggested_action: "Release this Elastic IP.",
    estimated_monthly_cost: 3.65,
  });
  const inspector = () => screen.getByRole("complementary", { name: /selected finding/i });

  it("keeps the prose out of the table — the whole reason this is master/detail", () => {
    render(<ResourceTable resources={[eip, resource()]} asOf={SCANNED_AT} />);

    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent.trim());
    expect(headers).not.toContain("Why it may cost money");
    expect(headers).not.toContain("Suggested action");
    // Present once, in the inspector — not once per row.
    expect(screen.getAllByText("AWS charges hourly for every public IPv4 address.")).toHaveLength(1);
  });

  it("selects the first finding, so the panel is never empty on load", () => {
    render(<ResourceTable resources={[eip, resource()]} asOf={SCANNED_AT} />);

    expect(within(inspector()).getByText("left-over-lab-ip")).toBeInTheDocument();
    expect(within(inspector()).getByText("Release this Elastic IP.")).toBeInTheDocument();
    expect(screen.getAllByRole("row")[1]).toHaveAttribute("aria-selected", "true");
  });

  it("moves the inspector to the row you click", async () => {
    const user = userEvent.setup();
    render(<ResourceTable resources={[eip, resource()]} asOf={SCANNED_AT} />);

    await user.click(screen.getAllByRole("row")[2]);

    expect(within(inspector()).getByText("stop it")).toBeInTheDocument();
    expect(screen.getAllByRole("row")[2]).toHaveAttribute("aria-selected", "true");
    expect(screen.getAllByRole("row")[1]).toHaveAttribute("aria-selected", "false");
  });

  it("moves the selection with the arrow keys, and is one tab stop", async () => {
    const user = userEvent.setup();
    render(<ResourceTable resources={[eip, resource()]} asOf={SCANNED_AT} />);

    // Roving tabindex: 15 findings must not become 15 tab stops.
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.filter((r) => r.getAttribute("tabindex") === "0")).toHaveLength(1);

    rows[0].focus();
    await user.keyboard("{ArrowDown}");
    expect(rows[1]).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowUp}");
    expect(rows[0]).toHaveAttribute("aria-selected", "true");
  });

  it("does not run off the ends", async () => {
    const user = userEvent.setup();
    render(<ResourceTable resources={[eip, resource()]} asOf={SCANNED_AT} />);
    const rows = screen.getAllByRole("row").slice(1);

    rows[0].focus();
    await user.keyboard("{ArrowUp}");
    expect(rows[0]).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{End}{ArrowDown}");
    expect(rows[rows.length - 1]).toHaveAttribute("aria-selected", "true");
  });

  it("re-homes the selection when a filter removes the selected row", () => {
    const { rerender } = render(<ResourceTable resources={[eip, resource()]} asOf={SCANNED_AT} />);
    expect(within(inspector()).getByText("left-over-lab-ip")).toBeInTheDocument();

    // Dashboard's account filter can drop the selected finding at any time. A
    // stored selection would leave the panel describing a row that is gone.
    rerender(<ResourceTable resources={[resource()]} asOf={SCANNED_AT} />);

    expect(within(inspector()).getByText("tutorial-web-server")).toBeInTheDocument();
    expect(screen.queryByText("left-over-lab-ip")).not.toBeInTheDocument();
  });

  it("shows the cost-relevant spec, which nothing rendered before", () => {
    render(
      <ResourceTable
        resources={[resource({ details: { instance_type: "t3.micro" } })]}
        asOf={SCANNED_AT}
      />
    );

    expect(within(inspector()).getByText("Instance type")).toBeInTheDocument();
    expect(within(inspector()).getByText("t3.micro")).toBeInTheDocument();
  });
});
