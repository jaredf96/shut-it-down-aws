import { useId, useRef, useState } from "react";
import Icon from "./Icon.jsx";
import RiskBadge, { RISK_ORDER } from "./RiskBadge.jsx";

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

// Riskiest first — the order the filter offers its levels in.
const RISK_LEVELS = Object.keys(RISK_ORDER).sort((a, b) => RISK_ORDER[a] - RISK_ORDER[b]);

// Written out whole because Tailwind emits only the class names it can find in
// the source: a composed `bg-${tone}` would never reach the stylesheet.
const RISK_DOT = { HIGH: "bg-critical", REVIEW: "bg-info", MEDIUM: "bg-warning", LOW: "bg-success" };

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

/**
 * What each column sorts by, and which way a first click sorts it. A larger
 * value is further along — riskier, older, dearer — so "descending" means what
 * it says. `null` is a value the scan could not give, and it sorts last in both
 * directions: an unpriced finding is not a free one, and a resource whose API
 * reports no creation time is not a new one.
 */
const SORTS = {
  type: { first: "ascending", value: (r) => r.resource_type || null },
  name: { first: "ascending", value: (r) => r.name || r.resource_id || null },
  account: { first: "ascending", value: (r) => r.account_label || r.account_id || null },
  region: { first: "ascending", value: (r) => r.region || null },
  status: { first: "ascending", value: (r) => r.status || null },
  age: {
    first: "descending",
    value: (r) => {
      const created = Date.parse(r.created_at);
      return Number.isNaN(created) ? null : -created; // created earlier is older
    },
  },
  risk: {
    first: "descending",
    value: (r) => {
      const rank = RISK_ORDER[r.risk_level];
      return typeof rank === "number" ? -rank : null; // rank 0 is the riskiest
    },
  },
  cost: { first: "descending", value: (r) => r.estimated_monthly_cost ?? null },
};

// Dashboard hands the findings over already in this order, so the default sort
// renders them exactly as they arrived.
const DEFAULT_SORT = { key: "risk", dir: "descending" };

// The direction flips the comparison, not the result, and Array#sort is stable:
// ties keep the risk order they arrived in, whichever way a column is sorted.
function compareBy({ key, dir }) {
  const { value } = SORTS[key];
  const sign = dir === "ascending" ? 1 : -1;
  return (a, b) => {
    const x = value(a);
    const y = value(b);
    if (x === null || y === null) return (x === null) - (y === null);
    return sign * (typeof x === "string" ? collator.compare(x, y) : x - y);
  };
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
  const [sortChoice, setSortChoice] = useState(DEFAULT_SORT);
  const [riskChoice, setRiskChoice] = useState("all");
  const rowRefs = useRef(new Map());
  const filterId = useId();

  const list = resources || [];
  const showAccount = list.some((r) => r.account_label || r.account_id);
  const counts = Object.fromEntries(
    RISK_LEVELS.map((level) => [level, list.filter((r) => r.risk_level === level).length])
  );

  // The dashboard can swap the findings out from under either choice: another
  // account view, a saved scan, an empty one. A level that now matches nothing
  // would hide every row under a message saying there are none, and a sort on a
  // column no longer shown would order the rows by nothing on screen. So a choice
  // that stops applying is cleared, not merely overridden. Left stored, the filter
  // would show All while holding High, and the next scan with a HIGH finding
  // would quietly hide everything else again — and clicking All could not clear
  // it, because a radio that is already checked fires no change. Cleared during
  // render rather than in an effect, so no committed render holds one choice
  // while showing another.
  const staleRisk = riskChoice !== "all" && !counts[riskChoice];
  const staleSort = sortChoice.key === "account" && !showAccount;
  if (staleRisk) setRiskChoice("all");
  if (staleSort) setSortChoice(DEFAULT_SORT);
  const risk = staleRisk ? "all" : riskChoice;
  const sort = staleSort ? DEFAULT_SORT : sortChoice;

  if (list.length === 0) {
    return (
      <p className="empty">
        <Icon name="check" size={18} /> No resources found. Nothing obvious is costing you money.
      </p>
    );
  }

  const scannedAt = asOf ? new Date(asOf) : new Date();

  // Derived once. Rendering, the selection fallback and the arrow keys all read
  // this array, so the order on screen is the order you move through.
  const rows = list.filter((r) => risk === "all" || r.risk_level === risk).sort(compareBy(sort));

  // Derived, never stored: a filter can remove the selected row at any time, and
  // a stored selection would then describe a finding that is no longer on screen.
  const selected = rows.find((r) => keyOf(r) === selectedKey) || rows[0];
  const selectedK = keyOf(selected);

  const choices = [
    { level: "all", label: "All", count: list.length },
    ...RISK_LEVELS.map((level) => ({
      level,
      label: level[0] + level.slice(1).toLowerCase(),
      count: counts[level],
    })),
  ];

  function sortBy(key) {
    setSortChoice(
      sort.key === key
        ? { key, dir: sort.dir === "ascending" ? "descending" : "ascending" }
        : { key, dir: SORTS[key].first }
    );
  }

  function select(index) {
    const k = keyOf(rows[index]);
    setSelectedKey(k);
    rowRefs.current.get(k)?.focus();
  }

  // Roving tabindex: the table is one tab stop and the arrows move within it,
  // so 15 findings do not become 15 stops between the scan and the next control.
  function onRowKeyDown(e, index) {
    const moves = {
      ArrowDown: Math.min(index + 1, rows.length - 1),
      ArrowUp: Math.max(index - 1, 0),
      Home: 0,
      End: rows.length - 1,
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
      className="findings grid gap-x-4 gap-y-3 items-start lg:grid-cols-[minmax(0,1fr)_340px]"
      data-scene="findings"
    >
      {/* Native radios: one tab stop, arrow keys between levels, and a level
          with nothing in it is skipped rather than offering an empty table. */}
      <div
        className="flex flex-wrap items-center gap-1.5 lg:col-span-2"
        role="radiogroup"
        aria-labelledby={`${filterId}-label`}
        data-scene="findings-filter"
      >
        <span
          id={`${filterId}-label`}
          className="mr-1.5 text-xs font-bold uppercase tracking-wider text-text-subtle"
        >
          Risk
        </span>
        {choices.map(({ level, label, count }) => (
          <label
            key={level}
            className="relative inline-flex cursor-pointer select-none items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1 text-xs font-semibold text-text-muted hover:border-border-strong hover:text-text has-checked:border-accent has-checked:bg-accent/15 has-checked:text-text has-focus-visible:[box-shadow:var(--ring)] has-disabled:cursor-not-allowed has-disabled:opacity-45"
            data-scene={`findings-filter-${level.toLowerCase()}`}
            data-scene-state={level === risk ? "on" : "off"}
          >
            <input
              type="radio"
              className="sr-only"
              name={`${filterId}-risk`}
              value={level}
              checked={level === risk}
              disabled={count === 0}
              onChange={() => setRiskChoice(level)}
            />
            {level !== "all" && (
              <span className={`size-2 rounded-full ${RISK_DOT[level]}`} aria-hidden="true" />
            )}
            {label} <span className="font-mono tabular-nums text-text-subtle">{count}</span>
          </label>
        ))}
      </div>

      <div className="table-wrapper">
        <table className="resource-table" role="grid" aria-label="Findings from the last scan">
          <thead>
            <tr>
              <SortHeader column="type" sort={sort} onSort={sortBy}>
                Type
              </SortHeader>
              <SortHeader column="name" sort={sort} onSort={sortBy}>
                Name / ID
              </SortHeader>
              {showAccount && (
                <SortHeader
                  column="account"
                  sort={sort}
                  onSort={sortBy}
                  data-scene="findings-account-header"
                >
                  Account
                </SortHeader>
              )}
              <SortHeader column="region" sort={sort} onSort={sortBy}>
                Region
              </SortHeader>
              <SortHeader column="status" sort={sort} onSort={sortBy}>
                Status
              </SortHeader>
              <SortHeader column="age" sort={sort} onSort={sortBy}>
                Age
              </SortHeader>
              <SortHeader column="risk" sort={sort} onSort={sortBy}>
                Risk
              </SortHeader>
              <SortHeader
                column="cost"
                sort={sort}
                onSort={sortBy}
                title="Minimum monthly exposure — usage-based charges not included."
              >
                Min. $/mo
              </SortHeader>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
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

/**
 * A header the table can be sorted by. The state lives in `aria-sort` on the
 * cell, never in the label, so the header still reads "Age" to a test and to a
 * screen reader alike.
 *
 * The button is reset down to the header's own type, so the label lays out
 * exactly as the bare text did, and the arrow is positioned into the cell's
 * right padding rather than set beside the label. In the flow it would add its
 * width to every column's minimum, and at 1920px the table already wraps
 * `us-east-1` — the columns it widened would push more cells onto a second line.
 *
 * Gap plus arrow (2px + 11px) must stay inside that 14px padding. A label that
 * wraps fills its whole column, so anything wider pushes the last column's arrow
 * past the table's edge — invisible, but it scrolls `.table-wrapper` sideways.
 * At 4px + 12px it measured 1008 against 1006.
 */
function SortHeader({ column, sort, onSort, children, ...rest }) {
  const active = sort.key === column;
  const icon = !active ? "arrowUpDown" : sort.dir === "ascending" ? "arrowUp" : "arrowDown";
  return (
    <th aria-sort={active ? sort.dir : undefined} {...rest}>
      <button
        type="button"
        className={`group relative m-0 inline-block cursor-pointer border-0 bg-transparent p-0 text-left [font:inherit] [letter-spacing:inherit] [text-transform:inherit] ${
          active ? "text-text" : "[color:inherit] hover:text-text"
        }`}
        data-scene={`findings-sort-${column}`}
        data-scene-state={active ? sort.dir : "none"}
        onClick={() => onSort(column)}
      >
        {children}
        <Icon
          name={icon}
          size={11}
          className={`absolute top-1/2 left-full ml-0.5 -translate-y-1/2 ${
            active ? "text-accent" : "opacity-0 group-hover:opacity-60 group-focus-visible:opacity-60"
          }`}
        />
      </button>
    </th>
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
