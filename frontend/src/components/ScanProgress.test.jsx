/**
 * The bar must visibly finish.
 *
 * It eases toward a 90% cap while the outcome is unknown, and the original
 * version was simply unmounted the moment results arrived — so it vanished at
 * 90% and read as an interrupted scan.
 *
 * The first fix was itself buggy: setting 100% while the easing interval was
 * still running got clamped straight back to 90 on the next tick. These tests
 * pin both the completion and the teardown ordering.
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ScanProgress from "./ScanProgress.jsx";

const fillWidth = () =>
  parseFloat(document.querySelector(".scan-progress__fill").style.width);

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("ScanProgress", () => {
  it("advances but never passes the cap while the outcome is unknown", () => {
    render(<ScanProgress done={false} />);
    act(() => vi.advanceTimersByTime(10_000));

    expect(fillWidth()).toBeGreaterThan(50);
    expect(fillWidth()).toBeLessThanOrEqual(90);
  });

  it("fills to 100% when the scan completes", () => {
    const { rerender } = render(<ScanProgress done={false} />);
    act(() => vi.advanceTimersByTime(2000));
    expect(fillWidth()).toBeLessThan(100);

    rerender(<ScanProgress done={true} />);
    expect(fillWidth()).toBe(100);
  });

  it("stays at 100% — the easing interval must not clamp it back", () => {
    const { rerender } = render(<ScanProgress done={false} />);
    act(() => vi.advanceTimersByTime(2000));
    rerender(<ScanProgress done={true} />);

    // The exact regression: a few more ticks of the easing interval.
    act(() => vi.advanceTimersByTime(450));
    expect(fillWidth()).toBe(100);
  });

  it("announces completion instead of a stage", () => {
    const { rerender } = render(<ScanProgress done={false} />);
    rerender(<ScanProgress done={true} />);
    expect(screen.getByText(/scan complete/i)).toBeInTheDocument();
  });

  it("calls onDone only after the completion beat, not immediately", () => {
    const onDone = vi.fn();
    const { rerender } = render(<ScanProgress done={false} onDone={onDone} />);
    rerender(<ScanProgress done={true} onDone={onDone} />);

    expect(onDone).not.toHaveBeenCalled(); // the bar is still on screen at 100%
    act(() => vi.advanceTimersByTime(600));
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("does not call onDone while the scan is still running", () => {
    const onDone = vi.fn();
    render(<ScanProgress done={false} onDone={onDone} />);
    act(() => vi.advanceTimersByTime(30_000));
    expect(onDone).not.toHaveBeenCalled();
  });
});
