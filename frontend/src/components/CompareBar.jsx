// Controls for picking two saved scans to compare.
function label(scan) {
  const when = new Date(scan.created_at);
  const time = Number.isNaN(when.getTime()) ? scan.created_at : when.toLocaleString();
  return `${time} (${scan.resource_count} resources)`;
}

export default function CompareBar({ scans, fromId, toId, onChangeFrom, onChangeTo, onCompare, busy }) {
  const sameScan = fromId && toId && fromId === toId;

  return (
    <div className="compare-bar">
      <span className="compare-bar__title">Compare scans</span>

      <label className="compare-bar__field">
        <span>From (older)</span>
        <select value={fromId || ""} onChange={(e) => onChangeFrom(e.target.value)}>
          {scans.map((s) => (
            <option key={s.scan_id} value={s.scan_id}>
              {label(s)}
            </option>
          ))}
        </select>
      </label>

      <span className="compare-bar__arrow">→</span>

      <label className="compare-bar__field">
        <span>To (newer)</span>
        <select value={toId || ""} onChange={(e) => onChangeTo(e.target.value)}>
          {scans.map((s) => (
            <option key={s.scan_id} value={s.scan_id}>
              {label(s)}
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
    </div>
  );
}
