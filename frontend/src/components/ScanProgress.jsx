import { useEffect, useState } from "react";

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

export default function ScanProgress() {
  const [pct, setPct] = useState(8);
  const [stage, setStage] = useState(0);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const start = performance.now();
    // Ease toward a cap so the bar never "completes" until real results
    // replace this component — fast at first, asymptotically slower.
    const bar = setInterval(() => {
      setPct((p) => (p >= 90 ? 90 : p + Math.max(0.5, (90 - p) * 0.05)));
    }, 150);
    const stg = setInterval(() => {
      setStage((s) => Math.min(s + 1, STAGES.length - 1));
    }, 1300);
    const clk = setInterval(() => setElapsed((performance.now() - start) / 1000), 100);
    return () => {
      clearInterval(bar);
      clearInterval(stg);
      clearInterval(clk);
    };
  }, []);

  return (
    <div className="scan-progress" role="status" aria-live="polite">
      <div className="scan-progress__row">
        <span className="scan-progress__stage">
          <span className="scan-progress__pulse" aria-hidden="true" />
          {STAGES[stage]}…
        </span>
        <span className="scan-progress__elapsed">{elapsed.toFixed(1)}s</span>
      </div>
      <div className="scan-progress__track">
        <div className="scan-progress__fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
