// Sidebar list of saved scans. Clicking one loads it into the table.
// Only rendered when the backend has persistence enabled.
function formatTime(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

// Compact "vs previous scan" badges. `delta` is null for the earliest scan.
function DeltaBadges({ delta }) {
  if (!delta) {
    return <span className="delta delta--baseline">baseline</span>;
  }
  const { added, removed, changed } = delta;
  if (added === 0 && removed === 0 && changed === 0) {
    return <span className="delta delta--none">no change</span>;
  }
  return (
    <span className="delta">
      {added > 0 && <span className="delta__chip delta__chip--added">+{added}</span>}
      {removed > 0 && <span className="delta__chip delta__chip--removed">−{removed}</span>}
      {changed > 0 && <span className="delta__chip delta__chip--changed">~{changed}</span>}
      <span className="delta__label">vs previous</span>
    </span>
  );
}

export default function ScanHistory({ scans, activeId, onSelect, onLive, viewingLive }) {
  return (
    <aside className="history">
      <div className="history__header">
        <h2>Scan history</h2>
        <button
          className={`history__live ${viewingLive ? "is-active" : ""}`}
          onClick={onLive}
        >
          Live
        </button>
      </div>

      {scans.length === 0 ? (
        <p className="history__empty">No saved scans yet. Run a scan to save one.</p>
      ) : (
        <ul className="history__list">
          {scans.map((s) => {
            const high = s.summary?.by_risk_level?.HIGH || 0;
            return (
              <li key={s.scan_id}>
                <button
                  className={`history__item ${s.scan_id === activeId ? "is-active" : ""}`}
                  onClick={() => onSelect(s.scan_id)}
                >
                  <span className="history__time">{formatTime(s.created_at)}</span>
                  <span className="history__counts">
                    {s.resource_count} resources
                    {high > 0 && <span className="history__high"> · {high} high</span>}
                  </span>
                  <DeltaBadges delta={s.vs_previous} />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </aside>
  );
}
