/**
 * The Min. $/mo tile's comparison with the scan before it.
 *
 * Two questions, and both are the difficulty. Which scan counts as "before": the
 * history list names it for every scan it holds, but the live scan on screen may
 * be in the list under its own id, in it under no id at all (the demo's live
 * scan is its newest fixture), or not in it. And whether the two can be compared
 * at all: only when both are known to have read everything (D21).
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ExposureCard from "./ExposureCard.jsx";

// Noon UTC, so the short dates read the same from UTC−11 to UTC+11.
const at = (day) => `2026-08-${day}T12:00:00.000Z`;
const summary = (cost) => ({ total_resources: 1, by_risk_level: {}, estimated_monthly_cost: cost });
const ref = (s) => ({
  scan_id: s.scan_id,
  created_at: s.created_at,
  summary: s.summary,
  complete: s.complete,
});
const saved = (day, cost, { id = `${at(day)}_${day}${day}${day}${day}`, complete = true } = {}) => ({
  scan_id: id,
  created_at: at(day),
  resource_count: 1,
  summary: summary(cost),
  complete,
  vs_previous: null,
  previous: null,
});
// Newest first, as GET /scans returns them, each naming the scan before it. The
// last keeps any `previous` it was given: the server names one past the page.
const history = (...scans) =>
  scans.map((s, i) => ({ ...s, previous: scans[i + 1] ? ref(scans[i + 1]) : s.previous }));

// The whole line, sign and amount included, not just the words naming the scan.
const change = (day) => screen.getByText(new RegExp(`vs Aug ${day} scan`)).closest("p");
const anyComparison = () => screen.queryByText(/vs Aug \d+ scan|Not compared/);

describe("ExposureCard", () => {
  it("compares with the scan before this one, not with a saved copy of it", () => {
    // The demo's live scan has a null id and its newest fixture's timestamp.
    // That fixture is this scan, so the comparison is with the one before.
    render(
      <ExposureCard
        summary={summary(123.3)}
        scans={history(saved(17, 123.3), saved(14, 91.8))}
        scanId={null}
        asOf={at(17)}
        complete
      />
    );

    expect(change(14)).toHaveTextContent("+$31.50 vs Aug 14 scan");
  });

  it("compares a persisted live scan through its saved copy, not by when the response landed", () => {
    // The server saves the scan before it answers, so by `asOf` alone the saved
    // copy would count as earlier and the scan would be compared with itself.
    render(
      <ExposureCard
        summary={summary(123.3)}
        scans={history(saved(17, 123.3, { id: "live" }), saved(14, 91.8))}
        scanId="live"
        asOf="2026-08-17T12:00:03.000Z"
        complete
      />
    );

    expect(change(14)).toHaveTextContent("+$31.50");
  });

  it("compares a saved scan with the one saved before it, and says when exposure fell", () => {
    const scans = history(saved(17, 123.3), saved(14, 91.8), saved(10, 100));
    render(
      <ExposureCard
        summary={summary(91.8)}
        scans={scans}
        scanId={scans[1].scan_id}
        asOf={scans[1].created_at}
      />
    );

    expect(change(10)).toHaveTextContent("−$8.20 vs Aug 10 scan");
  });

  it("compares the last scan on a page with the one before it, which the page does not hold", () => {
    // A full page of history ends somewhere. The server names that row's
    // predecessor anyway, and the tile has no other way to find it.
    const scans = history(saved(17, 123.3), { ...saved(14, 91.8), previous: ref(saved(10, 64.1)) });
    render(
      <ExposureCard
        summary={summary(91.8)}
        scans={scans}
        scanId={scans[1].scan_id}
        asOf={scans[1].created_at}
      />
    );

    expect(change(10)).toHaveTextContent("+$27.70 vs Aug 10 scan");
  });

  it("says no change rather than +$0.00", () => {
    render(
      <ExposureCard
        summary={summary(91.8)}
        scans={history(saved(14, 91.8))}
        scanId={null}
        asOf={at(17)}
        complete
      />
    );

    expect(change(14)).toHaveTextContent("No change vs Aug 14 scan");
    expect(screen.queryByText(/\$0\.00/)).not.toBeInTheDocument();
  });

  it("shows the figure alone when there is nothing earlier to compare with", () => {
    const { rerender } = render(
      <ExposureCard summary={summary(3.65)} scans={null} scanId={null} asOf={at(17)} complete />
    );
    expect(screen.getByText("$3.65")).toBeInTheDocument();
    expect(anyComparison()).not.toBeInTheDocument();

    rerender(
      <ExposureCard
        summary={summary(3.65)}
        scans={history(saved(17, 3.65))}
        scanId={null}
        asOf={at(17)}
        complete
      />
    );
    expect(anyComparison()).not.toBeInTheDocument();
  });

  it("does not compare a live scan that could not read everything", () => {
    render(
      <ExposureCard
        summary={summary(40)}
        scans={history(saved(14, 91.8), saved(10, 80), saved("07", 70))}
        scanId={null}
        asOf={at(17)}
        complete={false}
      />
    );

    expect(screen.getByText("Not compared: this scan is incomplete")).toBeInTheDocument();
    expect(screen.queryByText(/vs Aug 14 scan/)).not.toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("does not compare a saved scan that could not read everything, reopened from history", () => {
    // Reopened, a scan that missed a region used to compare as a complete one:
    // a green −$51.80 that was only the region it could not read.
    const scans = history(saved(17, 40, { complete: false }), saved(14, 91.8));
    render(
      <ExposureCard
        summary={summary(40)}
        scans={scans}
        scanId={scans[0].scan_id}
        asOf={scans[0].created_at}
      />
    );

    expect(screen.getByText("Not compared: this scan is incomplete")).toBeInTheDocument();
    expect(screen.queryByText(/51\.80/)).not.toBeInTheDocument();
  });

  it("does not compare with a scan that could not read everything, and names it", () => {
    // Otherwise the next scan reads the gap back as a rise.
    render(
      <ExposureCard
        summary={summary(91.8)}
        scans={history(saved(14, 40, { complete: false }))}
        scanId={null}
        asOf={at(17)}
        complete
      />
    );

    expect(screen.getByText("Not compared: the Aug 14 scan is incomplete")).toBeInTheDocument();
    expect(screen.queryByText(/51\.80/)).not.toBeInTheDocument();
  });

  it("says nothing either way about a scan saved before completeness was recorded", () => {
    const { rerender } = render(
      <ExposureCard
        summary={summary(123.3)}
        scans={history(saved(14, 91.8, { complete: null }))}
        scanId={null}
        asOf={at(17)}
        complete
      />
    );
    expect(anyComparison()).not.toBeInTheDocument();

    const legacy = history(saved(17, 123.3, { complete: null }), saved(14, 91.8));
    rerender(
      <ExposureCard
        summary={summary(123.3)}
        scans={legacy}
        scanId={legacy[0].scan_id}
        asOf={legacy[0].created_at}
      />
    );
    expect(anyComparison()).not.toBeInTheDocument();
  });

  it("does not compare with a predecessor that carries no cost", () => {
    const unpriced = { ...saved(14, 0), summary: { total_resources: 1, by_risk_level: {} } };
    render(
      <ExposureCard
        summary={summary(123.3)}
        scans={history(unpriced, saved(10, 64.1))}
        scanId={null}
        asOf={at(17)}
        complete
      />
    );

    expect(anyComparison()).not.toBeInTheDocument();
  });

  it("waits for a third scan before drawing a trend, and ends it on this one", () => {
    const { rerender } = render(
      <ExposureCard
        summary={summary(123.3)}
        scans={history(saved(14, 91.8))}
        scanId={null}
        asOf={at(17)}
        complete
      />
    );
    expect(screen.queryByRole("list")).not.toBeInTheDocument();

    rerender(
      <ExposureCard
        summary={summary(123.3)}
        scans={history(saved(14, 91.8), saved(10, 64.1))}
        scanId={null}
        asOf={at(17)}
        complete
      />
    );
    const values = within(screen.getByRole("list", { name: /last 3 scans/ }))
      .getAllByRole("listitem")
      .map((li) => li.textContent);
    expect(values).toEqual(["Aug 10: $64.10", "Aug 14: $91.80", "Aug 17: $123.30 (this scan)"]);
  });

  it("draws the trend only through complete scans", () => {
    // An incomplete scan ends the run rather than being drawn through: its dip is
    // a region it could not read, not a cost that fell.
    render(
      <ExposureCard
        summary={summary(123.3)}
        scans={history(
          saved(14, 91.8),
          saved(12, 88),
          saved(10, 40, { complete: false }),
          saved("08", 70),
          saved("06", 65)
        )}
        scanId={null}
        asOf={at(17)}
        complete
      />
    );

    const values = within(screen.getByRole("list", { name: /last 3 scans/ }))
      .getAllByRole("listitem")
      .map((li) => li.textContent);
    expect(values).toEqual(["Aug 12: $88.00", "Aug 14: $91.80", "Aug 17: $123.30 (this scan)"]);
  });

  it("keeps a scan saved in the same millisecond in the trend, so an incomplete one still ends it", () => {
    // Two scans saved in the same millisecond share a `created_at`; only the
    // list's own order, by full scan_id, says which came first.
    const scans = history(
      saved(17, 123.3, { id: `${at(17)}_bbbbbbbb` }),
      saved(17, 40, { id: `${at(17)}_aaaaaaaa`, complete: false }),
      saved(14, 91.8),
      saved(10, 64.1)
    );
    render(
      <ExposureCard
        summary={summary(123.3)}
        scans={scans}
        scanId={scans[0].scan_id}
        asOf={scans[0].created_at}
      />
    );

    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.getByText("Not compared: the Aug 17 scan is incomplete")).toBeInTheDocument();
  });

  it("keeps the trend to the last twelve scans", () => {
    // Aug 1 to 15, newest first, as the list endpoint returns them.
    const scans = history(
      ...Array.from({ length: 15 }, (_, i) => saved(String(i + 1).padStart(2, "0"), 50 + i)).reverse()
    );
    render(
      <ExposureCard summary={summary(99)} scans={scans} scanId={null} asOf={at(17)} complete />
    );

    const items = within(screen.getByRole("list", { name: /last 12 scans/ })).getAllByRole(
      "listitem"
    );
    expect(items).toHaveLength(12);
    expect(items[0]).toHaveTextContent("Aug 5: $54.00");
    expect(items[11]).toHaveTextContent("Aug 17: $99.00 (this scan)");
  });
});
