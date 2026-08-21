import RiskBadge from "./RiskBadge.jsx";

const MS_PER_DAY = 86_400_000;

// Age is measured against the scan, not against now: a saved scan should read
// the same tomorrow as it did the day it ran, and the demo's fixture ages would
// otherwise creep upward every day and outrun the committed screenshots.
function formatAge(r, asOf) {
  if (!r.created_at) {
    return { text: "—", title: "This AWS API does not report a creation time." };
  }
  const created = new Date(r.created_at);
  if (Number.isNaN(created.getTime())) {
    return { text: "—", title: "Unreadable creation time." };
  }
  const days = Math.max(0, Math.floor((asOf - created) / MS_PER_DAY));
  return {
    text: days < 1 ? "<1d" : `${days}d`,
    title: `Created ${created.toLocaleString()}`,
  };
}

// A floor, not a forecast. Hourly rates, EBS GB-month storage and RDS allocated
// storage are priced; NAT data processing and S3 storage are not, so the real
// bill can only be higher than this. Labelling it an estimate implied a
// precision the model does not have.
function formatCost(r) {
  if (r.estimated_monthly_cost === null || r.estimated_monthly_cost === undefined) {
    return { text: "—", title: "Not priced — this resource's cost depends on usage we cannot see." };
  }
  return {
    text: `$${r.estimated_monthly_cost.toFixed(2)}`,
    title:
      `At least $${r.estimated_monthly_cost.toFixed(2)}/month at ${r.cost_source || "static"} ` +
      "list prices. Usage-based charges are not included, so the real cost is higher.",
  };
}

// Table view of scanned resources. Read-only — no action buttons yet.
// The Account column only appears when resources are tagged (multi-account).
// `asOf` is when the scan ran; it defaults to now for a scan that just did.
export default function ResourceTable({ resources, asOf }) {
  if (!resources || resources.length === 0) {
    return <p className="empty">No resources found. 🎉 Nothing obvious is costing you money.</p>;
  }

  const showAccount = resources.some((r) => r.account_label || r.account_id);
  const scannedAt = asOf ? new Date(asOf) : new Date();

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
            <th>Age</th>
            <th>Risk</th>
            <th title="Minimum monthly exposure — usage-based charges not included.">
              Min. $/mo
            </th>
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
              <td className="cell-age" title={formatAge(r, scannedAt).title}>
                {formatAge(r, scannedAt).text}
              </td>
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
