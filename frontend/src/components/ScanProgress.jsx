import { useEffect, useRef, useState } from "react";

// Activity indicator shown while a scan is in flight. The backend returns the
// whole scan in one response (no streaming), so the bar is paced to the typical
// ~12s scan rather than wired to true per-stage progress; the elapsed timer is
// real. Stages mirror the actual scanner order for a believable live readout.
const STAGES = [
  "Discovering enabled regions",
  "Scanning EC2 instances",
  "Checking EBS volumes",
  "Auditing Elastic IPs",
  "Inspecting NAT gateways",
  "Enumerating load balancers",
  "Scanning RDS databases",
  "Listing S3 buckets",
  "Estimating monthly cost",
];

// How long the finished bar stays on screen. Long enough to read as completion,
// short enough not to delay the results.
const COMPLETE_MS = 550;

/**
 * @param {object} props
 * @param {boolean} props.done  the scan has returned; finish the bar
 * @param {() => void} props.onDone  called once the completion beat has played
 */
export default function ScanProgress({ done = false, onDone }) {
  const [pct, setPct] = useState(8);
  const [stage, setStage] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const timers = useRef([]);

  const stopTimers = () => {
    timers.current.forEach(clearInterval);
    timers.current = [];
  };

  useEffect(() => {
    const start = performance.now();
    // Ease toward a cap while the outcome is unknown — fast at first,
    // asymptotically slower. The remaining 10% belongs to `done`.
    timers.current = [
      setInterval(() => {
        setPct((p) => (p >= 90 ? 90 : p + Math.max(0.5, (90 - p) * 0.05)));
      }, 150),
      setInterval(() => {
        setStage((s) => Math.min(s + 1, STAGES.length - 1));
      }, 1300),
      setInterval(() => setElapsed((performance.now() - start) / 1000), 100),
    ];
    return stopTimers;
  }, []);

  // Finish the bar rather than yanking it away mid-fill: a progress indicator
  // that vanishes at 90% reads as an interrupted scan, not a completed one.
  //
  // The easing interval must be stopped first — it clamps to 90 on every tick,
  // so setting 100 while it runs is immediately undone.
  useEffect(() => {
    if (!done) return;
    stopTimers();
    setPct(100);
    setStage(STAGES.length - 1);
    const t = setTimeout(() => onDone?.(), COMPLETE_MS);
    return () => clearTimeout(t);
  }, [done, onDone]);

  return (
    <div className="scan-progress" role="status" aria-live="polite">
      <div className="scan-progress__row">
        <span className="scan-progress__stage">
          {!done && <span className="scan-progress__pulse" aria-hidden="true" />}
          {done ? "Scan complete" : `${STAGES[stage]}…`}
        </span>
        <span className="scan-progress__elapsed">{elapsed.toFixed(1)}s</span>
      </div>
      <div
        className="scan-progress__track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
      >
        <div
          className={`scan-progress__fill${done ? " is-complete" : ""}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
