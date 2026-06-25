import RiskBadge from "./RiskBadge.jsx";

function formatTime(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

// Compact table of resources for the Added / Removed sections.
function ResourceRows({ resources }) {
  return (
    <table className="diff-table">
      <tbody>
        {resources.map((r) => (
          <tr key={`${r.resource_type}-${r.region}-${r.resource_id}`}>
            <td>{r.resource_type}</td>
            <td className="diff-table__name">{r.name || r.resource_id}</td>
            <td>{r.region}</td>
            <td>
              <RiskBadge level={r.risk_level} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Section({ title, tone, items, render }) {
  return (
    <section className="diff-section">
      <h3 className={`diff-section__title diff-section__title--${tone}`}>
        {title} <span className="diff-section__count">({items.length})</span>
      </h3>
      {items.length === 0 ? (
        <p className="diff-section__empty">None</p>
      ) : (
        render(items)
      )}
    </section>
  );
}

// Renders one "changed" row: which fields moved, with from → to values.
function ChangeRows({ items }) {
  return (
    <table className="diff-table">
      <tbody>
        {items.map(({ resource, changes }) => (
          <tr key={`${resource.resource_type}-${resource.region}-${resource.resource_id}`}>
            <td>{resource.resource_type}</td>
            <td className="diff-table__name">{resource.name || resource.resource_id}</td>
            <td>{resource.region}</td>
            <td className="diff-table__changes">
              {Object.entries(changes).map(([field, { from, to }]) => (
                <div key={field} className="diff-change">
                  <span className="diff-change__field">{field}</span>
                  {field === "risk_level" ? (
                    <span className="diff-change__values">
                      <RiskBadge level={from} /> <span className="diff-change__arrow">→</span>{" "}
                      <RiskBadge level={to} />
                    </span>
                  ) : (
                    <span className="diff-change__values">
                      <code>{String(from)}</code>{" "}
                      <span className="diff-change__arrow">→</span> <code>{String(to)}</code>
                    </span>
                  )}
                </div>
              ))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function DiffView({ diff, onClose }) {
  const { from, to, summary } = diff;

  return (
    <div className="diff">
      <div className="diff__header">
        <div>
          <h2>Changes</h2>
          <p className="diff__range">
            {formatTime(from.created_at)} <span className="diff-change__arrow">→</span>{" "}
            {formatTime(to.created_at)}
          </p>
        </div>
        <button className="diff__close" onClick={onClose}>
          ✕ Close
        </button>
      </div>

      <div className="diff__chips">
        <span className="diff-chip diff-chip--added">+{summary.added} added</span>
        <span className="diff-chip diff-chip--removed">−{summary.removed} removed</span>
        <span className="diff-chip diff-chip--changed">~{summary.changed} changed</span>
        <span className="diff-chip diff-chip--unchanged">={summary.unchanged} unchanged</span>
      </div>

      <Section
        title="Added"
        tone="added"
        items={diff.added}
        render={(items) => <ResourceRows resources={items} />}
      />
      <Section
        title="Removed"
        tone="removed"
        items={diff.removed}
        render={(items) => <ResourceRows resources={items} />}
      />
      <Section
        title="Changed"
        tone="changed"
        items={diff.changed}
        render={(items) => <ChangeRows items={items} />}
      />
    </div>
  );
}
