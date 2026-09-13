import Icon from "./Icon.jsx";

// Two points are a delta, which the line under the label already states; the
// sparkline waits for a third. Twelve is as much history as a tile can carry.
const MIN_POINTS = 3;
const MAX_POINTS = 12;

const money = (n) => `$${n.toFixed(2)}`;
const day = (iso) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
const priced = (scan) => Number.isFinite(scan?.summary?.estimated_monthly_cost);

/**
 * The Min. $/mo tile, and how that floor moved since the scan before this one.
 *
 * Two scans are compared only when both are known to have read everything
 * (`complete`, D21). A region, scanner or account a scan could not read lowers
 * its total, so comparing it would render "couldn't see" as a change. A scan
 * saved before that was recorded (`complete: null`) cannot be vouched for
 * either way, so it is not compared and nothing is said about it.
 *
 * "Before" is the history list's own `previous` for a scan in the list, which
 * the server names even for the last row of a page. An unsaved live scan is not
 * in the list, so its predecessor is the latest listed scan that ran strictly
 * earlier — by time, not position: the demo's live scan is its newest saved
 * fixture under a null id, and position would compare it with itself.
 *
 * `complete` is the live scan's own verdict; a scan found in the list carries
 * its own.
 */
export default function ExposureCard({ summary, scans, scanId, asOf, complete = null }) {
  const cost = Number(summary.estimated_monthly_cost);
  const list = scans || [];
  const index = scanId ? list.findIndex((s) => s.scan_id === scanId) : -1;
  const self = index === -1 ? null : list[index];
  const ranAt = self ? self.created_at : asOf;
  const thisComplete = self ? self.complete : complete;

  // Everything saved before this scan, newest first. For a scan in the list
  // that is the list's own order — the server's, by full `scan_id`, the order
  // `previous` follows. Two scans saved in the same millisecond share a
  // `created_at`, so choosing by time would drop this one's true predecessor.
  // An unsaved live scan is not in the list, so for it the cut is by time.
  const earlier = self
    ? list.slice(index + 1)
    : list.filter((s) => Date.parse(s.created_at) < Date.parse(asOf));
  const previous = self ? self.previous : earlier[0] || null;

  // The trend is the unbroken run of complete, priced scans ending at this one.
  // An incomplete or unrecorded scan ends it rather than being drawn through,
  // and the run cannot reach past the page the list was given.
  const run = [];
  if (thisComplete === true) {
    for (const s of earlier) {
      if (run.length === MAX_POINTS - 1 || s.complete !== true || !priced(s)) break;
      run.push(s);
    }
  }
  const points = [
    ...run.reverse().map((s) => ({ at: s.created_at, cost: s.summary.estimated_monthly_cost })),
    { at: ranAt, cost },
  ];

  let comparison = null;
  if (thisComplete === false) {
    comparison = <Note>Not compared: this scan is incomplete</Note>;
  } else if (thisComplete === true && previous?.complete === false) {
    comparison = <Note>Not compared: the {day(previous.created_at)} scan is incomplete</Note>;
  } else if (thisComplete === true && previous?.complete === true && priced(previous)) {
    comparison = <Change cost={cost} previous={previous} />;
  }

  return (
    <div className="summary-card">
      <div className="summary-card__value">{money(cost)}</div>
      <div className="summary-card__label">Min. $/mo</div>
      {comparison}
      {points.length >= MIN_POINTS && <Sparkline points={points} />}
    </div>
  );
}

function Note({ children }) {
  return <p className="mt-2 mb-0 text-xs text-text-muted">{children}</p>;
}

// Signed, named against the scan it is measured from, and coloured by whether
// the move is bad news — with the arrow and the sign carrying the direction, so
// the colour never does it alone. Rounded in cents first: 123.3 − 91.8 is
// 31.499999999999986, and a floor that moved by nothing must not read "+$0.00".
function Change({ cost, previous }) {
  const was = previous.summary.estimated_monthly_cost;
  const cents = Math.round((cost - was) * 100);
  const vs = `vs ${day(previous.created_at)} scan`;
  const title = `${money(was)} in the scan saved ${new Date(previous.created_at).toLocaleString()}`;

  if (cents === 0) {
    return (
      <p className="mt-2 mb-0 text-xs text-text-muted" title={title}>
        No change {vs}
      </p>
    );
  }

  const up = cents > 0;
  // In a tile too narrow for one line, the comparison drops under the amount
  // whole, rather than wrapping beside it.
  return (
    <p
      className="mt-2 mb-0 flex flex-wrap items-center gap-x-1 text-xs text-text-muted"
      title={title}
    >
      <span
        className={`inline-flex items-center gap-0.5 font-semibold ${up ? "text-critical" : "text-success"}`}
      >
        <Icon name={up ? "arrowUp" : "arrowDown"} size={12} />
        {up ? "+" : "−"}${(Math.abs(cents) / 100).toFixed(2)}
      </span>{" "}
      <span className="whitespace-nowrap">{vs}</span>
    </p>
  );
}

const W = 160;
const H = 28;
const PAD = 6; // the end dot's radius plus its ring, so neither is clipped

function Sparkline({ points }) {
  const costs = points.map((p) => p.cost);
  const lo = Math.min(...costs);
  const hi = Math.max(...costs);
  const last = points.length - 1;
  const step = (W - 2 * PAD) / last;
  const x = (i) => PAD + i * step;
  // An unchanged history is a level line through the middle, not one on the floor.
  const y = (c) => (hi === lo ? H / 2 : H - PAD - ((c - lo) / (hi - lo)) * (H - 2 * PAD));

  return (
    <>
      <svg
        className="mt-2 block h-auto w-full text-text-subtle"
        viewBox={`0 0 ${W} ${H}`}
        aria-hidden="true"
        focusable="false"
      >
        <polyline
          points={points.map((p, i) => `${x(i)},${y(p.cost)}`).join(" ")}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle
          cx={x(last)}
          cy={y(points[last].cost)}
          r="4"
          strokeWidth="2"
          className="fill-accent stroke-surface"
        />
        {/* Hover names each scan. The hit area is the point's whole column,
            not the 2px line. */}
        {points.map((p, i) => (
          <rect key={i} x={x(i) - step / 2} y="0" width={step} height={H} fill="transparent">
            <title>{`${money(p.cost)} · ${day(p.at)}`}</title>
          </rect>
        ))}
      </svg>
      {/* The values themselves, for anyone the drawing does not reach. */}
      <ul className="sr-only" aria-label={`Min. $/mo in the last ${points.length} scans`}>
        {points.map((p, i) => (
          <li key={i}>{`${day(p.at)}: ${money(p.cost)}${i === last ? " (this scan)" : ""}`}</li>
        ))}
      </ul>
    </>
  );
}
