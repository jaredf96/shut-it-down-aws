import RiskBadge from "./RiskBadge.jsx";

function formatCost(r) {
  if (r.estimated_monthly_cost === null || r.estimated_monthly_cost === undefined) {
    return { text: "—", title: "Cost depends on usage; not estimated." };
  }
  return {
    text: `$${r.estimated_monthly_cost.toFixed(2)}`,
    title: `~${r.cost_source || "static"} estimate / month`,
  };
}

// Table view of scanned resources. Read-only — no action buttons yet.
// The Account column only appears when resources are tagged (multi-account).
export default function ResourceTable({ resources }) {
  if (!resources || resources.length === 0) {
    return <p className="empty">No resources found. 🎉 Nothing obvious is costing you money.</p>;
  }

  const showAccount = resources.some((r) => r.account_label || r.account_id);

  return (
    <div className="table-wrapper">
      <table className="resource-table">
        <thead>
          <tr>
            <th>Type</th>
            <th>Name / ID</th>
            {showAccount && <th>Account</th>}
            <th>Region</th>
            <th>Status</th>
            <th>Risk</th>
            <th>Est. $/mo</th>
            <th>Why it may cost money</th>
            <th>Suggested action</th>
          </tr>
        </thead>
        <tbody>
          {resources.map((r) => (
            <tr key={`${r.account_id || ""}-${r.resource_type}-${r.resource_id}`}>
              <td>{r.resource_type}</td>
              <td>
                <div className="cell-name">{r.name || r.resource_id}</div>
                {r.name && <div className="cell-id">{r.resource_id}</div>}
              </td>
              {showAccount && (
                <td>
                  <div className="cell-name">{r.account_label || r.account_id}</div>
                  {r.account_label && <div className="cell-id">{r.account_id}</div>}
                </td>
              )}
              <td>{r.region}</td>
              <td>{r.status}</td>
              <td>
                <RiskBadge level={r.risk_level} />
              </td>
              <td className="cell-cost" title={formatCost(r).title}>
                {formatCost(r).text}
                {r.cost_source === "live" && <span className="cost-live"> live</span>}
              </td>
              <td className="cell-text">{r.monthly_cost_risk}</td>
              <td className="cell-text">{r.suggested_action}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
