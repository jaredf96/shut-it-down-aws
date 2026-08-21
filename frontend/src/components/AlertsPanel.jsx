import RiskBadge from "./RiskBadge.jsx";

const SEVERITY_META = {
  CRITICAL: { label: "Critical", icon: "🔴" },
  WARNING: { label: "Warning", icon: "🟠" },
  INFO: { label: "Info", icon: "🔵" },
};

const ORDER = ["CRITICAL", "WARNING", "INFO"];

// Banner-style panel summarizing alerts from the latest scan.
// Renders nothing when there are no alerts.
export default function AlertsPanel({ alerts }) {
  if (!alerts || alerts.length === 0) return null;

  const counts = alerts.reduce((acc, a) => {
    acc[a.severity] = (acc[a.severity] || 0) + 1;
    return acc;
  }, {});

  return (
    <section className="alerts">
      <div className="alerts__header">
        <h2>⚠️ Alerts ({alerts.length})</h2>
        <div className="alerts__counts">
          {ORDER.filter((s) => counts[s]).map((s) => (
            <span key={s} className={`alerts__count alerts__count--${s.toLowerCase()}`}>
              {SEVERITY_META[s].icon} {counts[s]} {SEVERITY_META[s].label}
            </span>
          ))}
        </div>
      </div>

      <ul className="alerts__list">
        {alerts.map((a) => (
          <li key={a.id} className={`alert alert--${a.severity.toLowerCase()}`}>
            <span className="alert__severity">{SEVERITY_META[a.severity]?.icon}</span>
            <div className="alert__body">
              <div className="alert__title">{a.title}</div>
              <div className="alert__message">{a.message}</div>
              <div className="alert__meta">
                <span className="alert__resource">
                  {a.resource_type} · {a.resource_id} · {a.region}
                </span>
                <RiskBadge level={a.risk_level} />
                {a.estimated_monthly_cost != null && (
                  <span
                    className="alert__cost"
                    title="Minimum monthly exposure — usage-based charges are not priced."
                  >
                    ≥${a.estimated_monthly_cost.toFixed(2)}/mo
                  </span>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
