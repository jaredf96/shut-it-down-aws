/**
 * DiffView renders real backend diff output.
 *
 * The component is driven by `demo-data/expected-diff.json`, produced by the
 * actual backend diff service, so this asserts the component can render what
 * the API really sends — added, removed, and changed together, including a
 * resource with more than one changed field.
 *
 * A crash here previously reached the browser: the demo provider supplied a
 * flat resource with a `changes` array, and `ChangeRows` destructures
 * `{ resource, changes }`.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import expectedDiff from "@demo-data/expected-diff.json";
import DiffView from "./DiffView.jsx";

function renderDiff(diff = expectedDiff) {
  return render(<DiffView diff={diff} onClose={vi.fn()} />);
}

describe("DiffView", () => {
  it("renders every bucket's counts", () => {
    renderDiff();
    const { added, removed, changed, unchanged } = expectedDiff.summary;
    expect(screen.getByText(`+${added} added`)).toBeInTheDocument();
    expect(screen.getByText(`−${removed} removed`)).toBeInTheDocument();
    expect(screen.getByText(`~${changed} changed`)).toBeInTheDocument();
    expect(screen.getByText(`=${unchanged} unchanged`)).toBeInTheDocument();
  });

  it("lists added resources by name", () => {
    renderDiff();
    for (const r of expectedDiff.added) {
      expect(screen.getAllByText(r.name || r.resource_id).length).toBeGreaterThan(0);
    }
  });

  it("lists removed resources by name", () => {
    renderDiff();
    for (const r of expectedDiff.removed) {
      expect(screen.getAllByText(r.name || r.resource_id).length).toBeGreaterThan(0);
    }
  });

  it("renders every changed field as a from → to pair", () => {
    renderDiff();
    const entry = expectedDiff.changed[0];

    // The fixture is built so this resource changed more than one field.
    expect(Object.keys(entry.changes).length).toBeGreaterThan(1);

    for (const [field, { from, to }] of Object.entries(entry.changes)) {
      expect(screen.getByText(field)).toBeInTheDocument();
      // risk_level renders as badges, status as <code>; both show the text.
      expect(screen.getAllByText(String(from)).length).toBeGreaterThan(0);
      expect(screen.getAllByText(String(to)).length).toBeGreaterThan(0);
    }
  });

  it("does not crash when a bucket is empty", () => {
    const empty = {
      ...expectedDiff,
      added: [],
      removed: [],
      changed: [],
      summary: { added: 0, removed: 0, changed: 0, unchanged: 3 },
    };
    expect(() => renderDiff(empty)).not.toThrow();
  });

  it("calls onClose when the close control is used", async () => {
    const onClose = vi.fn();
    render(<DiffView diff={expectedDiff} onClose={onClose} />);
    screen.getByRole("button", { name: /close/i }).click();
    expect(onClose).toHaveBeenCalled();
  });

  it("shows the scan range it is comparing", () => {
    renderDiff();
    const header = screen.getByRole("heading", { name: /changes/i }).closest("div");
    expect(within(header).getByText(/→/)).toBeInTheDocument();
  });
});
