/**
 * The two scan selects must constrain each other.
 *
 * Picking a newer scan as "from" (or an older one as "to") produced a
 * backwards diff — additions reported as removals — with nothing on screen
 * indicating the comparison was inverted.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import CompareBar from "./CompareBar.jsx";

const SCANS = [
  { scan_id: "newest", created_at: "2026-08-17T14:05:11.000Z", resource_count: 15 },
  { scan_id: "middle", created_at: "2026-08-15T09:00:00.000Z", resource_count: 14 },
  { scan_id: "oldest", created_at: "2026-08-14T08:12:44.000Z", resource_count: 14 },
];

function renderBar(props = {}) {
  return render(
    <CompareBar
      scans={SCANS}
      fromId="oldest"
      toId="newest"
      onChangeFrom={vi.fn()}
      onChangeTo={vi.fn()}
      onCompare={vi.fn()}
      busy={false}
      {...props}
    />
  );
}

const optionsOf = (labelText) =>
  [...screen.getByLabelText(labelText, { exact: false }).querySelectorAll("option")];

describe("CompareBar", () => {
  it("disables scans that are not older in the From select", () => {
    renderBar({ fromId: "oldest", toId: "middle" });
    const byId = Object.fromEntries(optionsOf("From").map((o) => [o.value, o]));

    expect(byId.oldest.disabled).toBe(false); // older than "middle"
    expect(byId.middle.disabled).toBe(true); // same instant
    expect(byId.newest.disabled).toBe(true); // newer — would invert the diff
  });

  it("disables scans that are not newer in the To select", () => {
    renderBar({ fromId: "middle", toId: "newest" });
    const byId = Object.fromEntries(optionsOf("To").map((o) => [o.value, o]));

    expect(byId.newest.disabled).toBe(false);
    expect(byId.middle.disabled).toBe(true);
    expect(byId.oldest.disabled).toBe(true); // older — would invert the diff
  });

  it("keeps the current selection selectable so the control never blanks", () => {
    renderBar({ fromId: "oldest", toId: "newest" });
    const from = screen.getByLabelText("From", { exact: false });
    const to = screen.getByLabelText("To", { exact: false });

    expect(from.value).toBe("oldest");
    expect(to.value).toBe("newest");
    expect([...from.querySelectorAll("option")].find((o) => o.value === "oldest").disabled).toBe(
      false
    );
  });

  it("refuses to compare a scan with itself", () => {
    renderBar({ fromId: "middle", toId: "middle" });
    expect(screen.getByRole("button", { name: /compare/i })).toBeDisabled();
    expect(screen.getByText(/pick two different scans/i)).toBeInTheDocument();
  });

  it("labels itself as a comparison, not a view of the current scan", () => {
    // The old wording read as a filter over what was already on screen.
    renderBar();
    expect(screen.getByText(/compare two scans/i)).toBeInTheDocument();
    expect(screen.getByText(/what changed between them/i)).toBeInTheDocument();
  });
});
