// Controls for picking two saved scans to compare.
//
// The two selects are constrained against each other: "from" cannot be a scan
// newer than "to", and vice versa. Allowing an inverted pair silently produced
// a backwards diff — additions reported as removals — with nothing on screen
// saying so.
function label(scan) {
  const when = new Date(scan.created_at);
  const time = Number.isNaN(when.getTime()) ? scan.created_at : when.toLocaleString();
  return `${time} (${scan.resource_count} resources)`;
}

const at = (scan) => new Date(scan.created_at).getTime();

export default function CompareBar({
  scans,
  fromId,
  toId,
  onChangeFrom,
  onChangeTo,
  onCompare,
  busy,
}) {
  const byId = Object.fromEntries(scans.map((s) => [s.scan_id, s]));
  const fromScan = byId[fromId];
  const toScan = byId[toId];
  const sameScan = fromId && toId && fromId === toId;

  // Disabled rather than hidden: the current selection always stays visible, so
  // the control can never end up showing a blank value.
  const invalidAsFrom = (s) => (toScan ? at(s) >= at(toScan) : false);
  const invalidAsTo = (s) => (fromScan ? at(s) <= at(fromScan) : false);

  return (
    <section className="compare-bar" aria-label="Compare two scans">
      <div className="compare-bar__intro">
        <span className="compare-bar__title">Compare two scans</span>
        <span className="compare-bar__sub">
          What changed between them — added, removed, and changed resources.
        </span>
      </div>

      <label className="compare-bar__field">
        <span>From (older)</span>
        <select value={fromId || ""} onChange={(e) => onChangeFrom(e.target.value)}>
          {scans.map((s) => (
            <option key={s.scan_id} value={s.scan_id} disabled={invalidAsFrom(s)}>
              {label(s)}
              {invalidAsFrom(s) ? " — not older" : ""}
            </option>
          ))}
        </select>
      </label>

      <span className="compare-bar__arrow">→</span>

      <label className="compare-bar__field">
        <span>To (newer)</span>
        <select value={toId || ""} onChange={(e) => onChangeTo(e.target.value)}>
          {scans.map((s) => (
            <option key={s.scan_id} value={s.scan_id} disabled={invalidAsTo(s)}>
              {label(s)}
              {invalidAsTo(s) ? " — not newer" : ""}
            </option>
          ))}
        </select>
      </label>

      <button
        className="compare-bar__button"
        onClick={onCompare}
        disabled={busy || sameScan || !fromId || !toId}
      >
        {busy ? "Comparing…" : "Compare"}
      </button>

      {sameScan && <span className="compare-bar__hint">Pick two different scans.</span>}
    </section>
  );
}
