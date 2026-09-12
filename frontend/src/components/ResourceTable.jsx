import { useRef, useState } from "react";
import Icon from "./Icon.jsx";
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

// Account is in the identity because the same id can exist in two accounts —
// the same 4-tuple the alert and diff engines key on.
const keyOf = (r) => `${r.account_id || ""}-${r.resource_type}-${r.resource_id}`;

// Turn `details` ({instance_type: "t3.micro"}) into readable rows. The scanners
// already put the cost-relevant spec here; until now nothing rendered it.
const DETAIL_LABELS = {
  instance_type: "Instance type",
  instance_class: "Instance class",
  engine: "Engine",
  allocated_storage_gb: "Allocated storage",
  size_gb: "Size",
  volume_type: "Volume type",
};
function detailRows(details) {
  if (!details || typeof details !== "object") return [];
  return Object.entries(details).map(([k, v]) => [
    DETAIL_LABELS[k] || k.replace(/_/g, " "),
    /_gb$/.test(k) ? `${v} GB` : String(v),
  ]);
}

/**
 * Findings as master/detail: every finding is one short row, and the two long
 * prose fields belong to whichever row is selected.
 *
 * They used to be columns. At 193px each they wrapped to six lines, which made
 * every row ~121px tall and the table 1874px — taller than any screen, so
 * reading it meant scrolling and *recording* it meant a long pan. Rows are a
 * single line now and the explanation sits beside them, which is also why this
 * is a side panel rather than an expanding row: an expanding row would put the
 * height straight back the moment anyone opened one.
 *
 * `asOf` is when the scan ran; ages are measured against it, never render time.
 */
export default function ResourceTable({ resources, asOf }) {
  const [selectedKey, setSelectedKey] = useState(null);
  const rowRefs = useRef(new Map());

  const list = resources || [];
  // Derived, never stored: a filter can remove the selected row at any time, and
  // a stored selection would then describe a finding that is no longer on screen.
  const selected = list.find((r) => keyOf(r) === selectedKey) || list[0];

  if (list.length === 0) {
    return (
      <p className="empty">
        <Icon name="check" size={18} /> No resources found. Nothing obvious is costing you money.
      </p>
    );
  }

  const showAccount = list.some((r) => r.account_label || r.account_id);
  const scannedAt = asOf ? new Date(asOf) : new Date();
  const selectedK = selected ? keyOf(selected) : null;

  function select(index) {
    const k = keyOf(list[index]);
    setSelectedKey(k);
    rowRefs.current.get(k)?.focus();
  }

  // Roving tabindex: the table is one tab stop and the arrows move within it,
  // so 15 findings do not become 15 stops between the scan and the next control.
  function onRowKeyDown(e, index) {
    const moves = {
      ArrowDown: Math.min(index + 1, list.length - 1),
      ArrowUp: Math.max(index - 1, 0),
      Home: 0,
      End: list.length - 1,
    };
    if (e.key in moves) {
      e.preventDefault();
      select(moves[e.key]);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      select(index);
    }
  }

  return (
    <div
      className="findings grid gap-4 items-start lg:grid-cols-[minmax(0,1fr)_340px]"
      data-scene="findings"
    >
      <div className="table-wrapper">
        <table className="resource-table" role="grid" aria-label="Findings from the last scan">
          <thead>
            <tr>
              <th>Type</th>
              <th>Name / ID</th>
              {showAccount && <th data-scene="findings-account-header">Account</th>}
              <th>Region</th>
              <th>Status</th>
              <th>Age</th>
              <th>Risk</th>
              <th title="Minimum monthly exposure — usage-based charges not included.">
                Min. $/mo
              </th>
            </tr>
          </thead>
          <tbody>
            {list.map((r, i) => {
              const k = keyOf(r);
              const isSelected = k === selectedK;
              return (
                <tr
                  key={k}
                  ref={(el) => {
                    if (el) rowRefs.current.set(k, el);
                    else rowRefs.current.delete(k);
                  }}
                  className={isSelected ? "is-selected" : ""}
                  data-scene="findings-row"
                  data-scene-selected={isSelected ? "true" : "false"}
                  aria-selected={isSelected}
                  tabIndex={isSelected ? 0 : -1}
                  onClick={() => select(i)}
                  onKeyDown={(e) => onRowKeyDown(e, i)}
                >
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
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Sticky so the explanation stays beside the row it explains, and so a
          taller inspector never drives the findings region's height. */}
      <aside
        className="findings__inspector sticky top-4 rounded-base border border-border bg-surface p-4 shadow-card"
        data-scene="findings-inspector"
        aria-live="polite"
        aria-label="Selected finding"
      >
        <div className="flex items-center gap-2">
          <RiskBadge level={selected.risk_level} />
          <span className="text-xs font-bold uppercase tracking-wider text-text-subtle">
            {selected.resource_type}
          </span>
        </div>

        <h3 className="mt-2 mb-0 text-base font-semibold leading-snug">
          {selected.name || selected.resource_id}
        </h3>
        <p className="mt-1 mb-3 font-mono text-xs break-all text-text-subtle">
          {selected.resource_id}
        </p>

        <dl className="m-0 grid grid-cols-2 gap-x-3 gap-y-2 border-t border-border pt-3 text-xs">
          <Fact label="Min. $/mo">
            <span className="cell-cost" title={formatCost(selected).title}>
              {formatCost(selected).text}
            </span>
          </Fact>
          <Fact label="Age">
            <span className="cell-age" title={formatAge(selected, scannedAt).title}>
              {formatAge(selected, scannedAt).text}
            </span>
          </Fact>
          <Fact label="Region">{selected.region}</Fact>
          <Fact label="Status">{selected.status}</Fact>
          {showAccount && (
            <Fact label="Account" wide>
              {selected.account_label || selected.account_id}
              {selected.account_label && (
                <span className="cell-id"> {selected.account_id}</span>
              )}
            </Fact>
          )}
          {detailRows(selected.details).map(([label, value]) => (
            <Fact key={label} label={label}>
              {value}
            </Fact>
          ))}
        </dl>

        <h4 className="mt-4 mb-1 text-xs font-bold uppercase tracking-wider text-text-subtle">
          Why it may cost money
        </h4>
        <p className="m-0 text-sm leading-normal text-text-muted">{selected.monthly_cost_risk}</p>

        <h4 className="mt-3 mb-1 text-xs font-bold uppercase tracking-wider text-text-subtle">
          Suggested action
        </h4>
        <p className="m-0 text-sm leading-normal text-text-muted">{selected.suggested_action}</p>
      </aside>
    </div>
  );
}

function Fact({ label, children, wide = false }) {
  return (
    <div className={wide ? "col-span-2" : ""}>
      <dt className="text-text-subtle">{label}</dt>
      <dd className="m-0 mt-0.5 text-text">{children}</dd>
    </div>
  );
}
