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

/**
 * Sort and risk filter. Both are a view over the findings the dashboard hands
 * in, and those arrive already in risk order — so the default has to render
 * them unchanged, and any other order has to keep ties the way they came.
 */
describe("ResourceTable sort and risk filter", () => {
  const eip = resource({
    resource_type: "Elastic IP",
    resource_id: "eipalloc-1",
    name: "left-over-lab-ip",
    status: "unassociated",
    risk_level: "HIGH",
    created_at: null,
    estimated_monthly_cost: 3.65,
  });
  const nat = resource({
    resource_type: "NAT Gateway",
    resource_id: "nat-1",
    name: "lab-vpc-nat",
    status: "available",
    risk_level: "HIGH",
    created_at: "2026-07-09T14:05:11.884Z", // 39 days
    estimated_monthly_cost: 32.85,
  });
  const bucket = resource({
    resource_type: "S3 Bucket",
    resource_id: "cloud-lab-artifacts",
    name: "cloud-lab-artifacts",
    status: "active",
    risk_level: "REVIEW",
    created_at: "2026-01-17T14:05:11.884Z", // 212 days
    estimated_monthly_cost: null,
    cost_source: "unknown",
  });
  const web = resource(); // MEDIUM, 87 days, $7.59
  const node = resource({
    resource_id: "i-0node",
    name: "workshop-node-01",
    status: "stopped",
    risk_level: "LOW",
    created_at: "2026-06-17T14:05:11.884Z", // 61 days
    estimated_monthly_cost: 0,
  });
  // In risk order, as Dashboard passes them.
  const FINDINGS = [eip, nat, bucket, web, node];

  const inspector = () => screen.getByRole("complementary", { name: /selected finding/i });
  const header = (name) => screen.getByRole("columnheader", { name });
  const sortBy = (user, name) => user.click(within(header(name)).getByRole("button"));
  const radio = (name) => screen.getByRole("radio", { name });
  const expectShown = (...names) =>
    expect(screen.getAllByRole("row").slice(1).map((r) => r.textContent)).toEqual(
      names.map((n) => expect.stringContaining(n))
    );

  it("renders the risk order it was given, marked as the sort in force", () => {
    render(<ResourceTable resources={FINDINGS} asOf={SCANNED_AT} />);

    expectShown("left-over-lab-ip", "lab-vpc-nat", "cloud-lab-artifacts", "tutorial-web-server", "workshop-node-01");
    expect(header("Risk")).toHaveAttribute("aria-sort", "descending");
    expect(radio("All 5")).toBeChecked();
  });

  it("sorts by cost, dearest first, and reverses on a second click", async () => {
    const user = userEvent.setup();
    render(<ResourceTable resources={FINDINGS} asOf={SCANNED_AT} />);

    await sortBy(user, "Min. $/mo");
    expect(header("Min. $/mo")).toHaveAttribute("aria-sort", "descending");
    expect(header("Risk")).not.toHaveAttribute("aria-sort");
    expectShown("lab-vpc-nat", "tutorial-web-server", "left-over-lab-ip", "workshop-node-01", "cloud-lab-artifacts");

    await sortBy(user, "Min. $/mo");
    expect(header("Min. $/mo")).toHaveAttribute("aria-sort", "ascending");
    // $0.00 is a price and sorts as one. Unpriced is not free, so it stays last.
    expectShown("workshop-node-01", "left-over-lab-ip", "tutorial-web-server", "lab-vpc-nat", "cloud-lab-artifacts");
  });

  it("sorts by age, oldest first, with no creation time last either way", async () => {
    const user = userEvent.setup();
    render(<ResourceTable resources={FINDINGS} asOf={SCANNED_AT} />);

    await sortBy(user, "Age");
    expectShown("cloud-lab-artifacts", "tutorial-web-server", "workshop-node-01", "lab-vpc-nat", "left-over-lab-ip");

    await sortBy(user, "Age");
    expectShown("lab-vpc-nat", "workshop-node-01", "tutorial-web-server", "cloud-lab-artifacts", "left-over-lab-ip");
  });

  it("keeps ties in the order they arrived, in both directions", async () => {
    const user = userEvent.setup();
    const bastion = resource({
      resource_type: "Elastic IP",
      resource_id: "eipalloc-2",
      name: "bastion-address",
      risk_level: "LOW",
      created_at: null,
      estimated_monthly_cost: 3.65,
    });
    render(<ResourceTable resources={[eip, web, bastion]} asOf={SCANNED_AT} />);

    await sortBy(user, "Min. $/mo");
    expectShown("tutorial-web-server", "left-over-lab-ip", "bastion-address");
    await sortBy(user, "Min. $/mo");
    expectShown("left-over-lab-ip", "bastion-address", "tutorial-web-server");
  });

  it("sorts a text column alphabetically", async () => {
    const user = userEvent.setup();
    render(<ResourceTable resources={FINDINGS} asOf={SCANNED_AT} />);

    await sortBy(user, "Type");
    expect(header("Type")).toHaveAttribute("aria-sort", "ascending");
    expectShown("tutorial-web-server", "workshop-node-01", "left-over-lab-ip", "lab-vpc-nat", "cloud-lab-artifacts");
  });

  it("keeps the sort out of the header text", async () => {
    const user = userEvent.setup();
    render(<ResourceTable resources={FINDINGS} asOf={SCANNED_AT} />);
    await sortBy(user, "Age");

    // The direction belongs to aria-sort. The labels are what the tests above
    // and every screen reader read, and an arrow character in them breaks both.
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent.trim());
    expect(headers).toEqual(["Type", "Name / ID", "Region", "Status", "Age", "Risk", "Min. $/mo"]);
  });

  it("filters to one risk level, and says how many each level holds", async () => {
    const user = userEvent.setup();
    render(<ResourceTable resources={FINDINGS} asOf={SCANNED_AT} />);

    await user.click(radio("High 2"));

    expectShown("left-over-lab-ip", "lab-vpc-nat");
    expect(radio("High 2")).toBeChecked();
    expect(radio("All 5")).not.toBeChecked();
  });

  it("disables a level with nothing in it", () => {
    render(<ResourceTable resources={[eip, web]} asOf={SCANNED_AT} />);

    expect(radio("Review 0")).toBeDisabled();
    expect(radio("Low 0")).toBeDisabled();
    expect(radio("High 1")).toBeEnabled();
  });

  it("clears a level that empties, so it can neither hide every row nor come back", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<ResourceTable resources={FINDINGS} asOf={SCANNED_AT} />);
    await user.click(radio("High 2"));

    // Dashboard's account view can take every HIGH finding out from under the
    // filter. Hiding every row would say "No resources found" over three.
    rerender(<ResourceTable resources={[bucket, web, node]} asOf={SCANNED_AT} />);
    expect(radio("All 3")).toBeChecked();
    expectShown("cloud-lab-artifacts", "tutorial-web-server", "workshop-node-01");
    expect(screen.queryByText(/no resources found/i)).not.toBeInTheDocument();

    // The view it fell back to is the one it keeps: HIGH findings coming back
    // must not quietly re-apply a filter the screen had stopped showing.
    rerender(<ResourceTable resources={FINDINGS} asOf={SCANNED_AT} />);
    expect(radio("All 5")).toBeChecked();
    expect(screen.getAllByRole("row")).toHaveLength(FINDINGS.length + 1);
  });

  it("clears a level when a scan comes back empty", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<ResourceTable resources={FINDINGS} asOf={SCANNED_AT} />);
    await user.click(radio("High 2"));

    rerender(<ResourceTable resources={[]} asOf={SCANNED_AT} />);
    rerender(<ResourceTable resources={FINDINGS} asOf={SCANNED_AT} />);

    expect(radio("All 5")).toBeChecked();
    expect(screen.getAllByRole("row")).toHaveLength(FINDINGS.length + 1);
  });

  it("drops a sort on the Account column once that column is gone", async () => {
    const user = userEvent.setup();
    const tagged = FINDINGS.map((r, i) => ({
      ...r,
      account_id: i % 2 ? "111122223333" : "444455556666",
      account_label: i % 2 ? "sandbox-lab" : "training-account",
    }));
    const { rerender } = render(<ResourceTable resources={tagged} asOf={SCANNED_AT} />);
    await sortBy(user, "Account");
    expect(header("Account")).toHaveAttribute("aria-sort", "ascending");

    // Findings that carry no account have no Account column to be sorted by.
    rerender(<ResourceTable resources={FINDINGS} asOf={SCANNED_AT} />);
    expect(header("Risk")).toHaveAttribute("aria-sort", "descending");

    rerender(<ResourceTable resources={tagged} asOf={SCANNED_AT} />);
    expect(header("Account")).not.toHaveAttribute("aria-sort");
    expect(header("Risk")).toHaveAttribute("aria-sort", "descending");
  });

  it("re-homes the selection when the risk filter hides the selected row", async () => {
    const user = userEvent.setup();
    render(<ResourceTable resources={FINDINGS} asOf={SCANNED_AT} />);

    await user.click(screen.getAllByRole("row")[4]); // tutorial-web-server, MEDIUM
    await user.click(radio("High 2"));

    expect(within(inspector()).getByText("left-over-lab-ip")).toBeInTheDocument();
    expect(screen.getAllByRole("row")[1]).toHaveAttribute("aria-selected", "true");
  });

  it("keeps the selected finding selected when the sort moves it", async () => {
    const user = userEvent.setup();
    render(<ResourceTable resources={FINDINGS} asOf={SCANNED_AT} />);

    await user.click(screen.getAllByRole("row")[2]); // lab-vpc-nat
    await sortBy(user, "Age"); // … which is fourth, oldest first

    expect(screen.getAllByRole("row")[4]).toHaveAttribute("aria-selected", "true");
    expect(within(inspector()).getByText("lab-vpc-nat")).toBeInTheDocument();
  });

  it("moves with the arrow keys in the order shown, not the order given", async () => {
    const user = userEvent.setup();
    render(<ResourceTable resources={FINDINGS} asOf={SCANNED_AT} />);
    await sortBy(user, "Min. $/mo"); // lab-vpc-nat, tutorial-web-server, …

    screen.getAllByRole("row")[1].focus();
    await user.keyboard("{ArrowDown}");

    expect(within(inspector()).getByText("tutorial-web-server")).toBeInTheDocument();
  });
});
