import { useEffect, useState } from "react";
import { capabilities, scanProvider } from "../data/scanProvider.js";

// Which finding is eligible for which action — the same preconditions the
// backend re-checks against live AWS before it will act.
const ELIGIBLE = {
  stop_ec2_instance: (r) => r.resource_type === "EC2 Instance" && r.status === "running",
  release_elastic_ip: (r) => r.resource_type === "Elastic IP" && r.status === "unassociated",
  delete_unattached_ebs_volume: (r) =>
    r.resource_type === "EBS Volume" && r.status === "available",
};

// Guided, auditable cleanup. Designed as a careful checklist: pick an action,
// type the exact resource id to confirm, dry-run first.
//
// Surfaces that may only preview (the public demo) still render the whole
// workflow — walking the gates is the point — but cannot execute.
export default function CleanupPanel({ isAdmin, resources = [] }) {
  const [catalog, setCatalog] = useState(null); // {enabled, actions, not_supported}
  const [audit, setAudit] = useState([]);
  const [action, setAction] = useState("");
  const [resourceId, setResourceId] = useState("");
  const [confirmId, setConfirmId] = useState("");
  const [region, setRegion] = useState("us-east-1");
  const [dryRun, setDryRun] = useState(true);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const data = await scanProvider.getCleanupActions();
      setCatalog(data);
      if (!action && data.actions.length) setAction(data.actions[0].key);
    } catch {
      setCatalog(null);
    }
    try {
      setAudit((await scanProvider.getCleanupAudit()).entries);
    } catch {
      setAudit([]);
    }
  }

  useEffect(() => {
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const mayPreview = isAdmin || capabilities.cleanupPreview;
  if (!mayPreview || catalog === null) return null;

  const selected = catalog.actions.find((a) => a.key === action);
  const confirmOk = resourceId.trim() !== "" && resourceId.trim() === confirmId.trim();

  // Findings this action could actually apply to, so nobody has to invent an ID.
  const eligible = resources.filter((r) => ELIGIBLE[action]?.(r));
  const previewOnly = !capabilities.cleanupExecute;

  function pickResource(id) {
    const match = resources.find((r) => r.resource_id === id);
    setResourceId(id);
    setConfirmId(""); // confirmation is always retyped by hand
    setResult(null);
    setError(null);
    if (match) setRegion(match.region);
  }

  async function run(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await scanProvider.executeCleanup({
        action,
        resource_id: resourceId.trim(),
        confirm_resource_id: confirmId.trim(),
        region: region.trim(),
        dry_run: previewOnly ? true : dryRun,
      });
      setResult(res);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="cleanup">
      <div className="cleanup__header">
        <h2>🧹 Guided cleanup</h2>
        <span
          className={`cleanup__flag ${catalog.enabled && !previewOnly ? "is-on" : "is-off"}`}
        >
          {previewOnly ? "preview only" : catalog.enabled ? "enabled" : "disabled in this environment"}
        </span>
      </div>

      {previewOnly ? (
        <p className="cleanup__note">
          Walk the real safety checks — action catalog, typed confirmation, and a live
          precondition re-check — and see the dry-run each would produce. Execution is
          unavailable here: this build holds no AWS credentials and targets no account.
          Every attempt that reaches the service is audited below, refusals included —
          try a resource ID that was not in the scan to see one.
        </p>
      ) : (
        !catalog.enabled && (
          <p className="cleanup__note">
            Mutating actions are off. Set <code>ENABLE_CLEANUP_ACTIONS=true</code> on the
            backend to enable them. You can still review the supported actions below.
          </p>
        )
      )}

      <form className="cleanup__form" onSubmit={run}>
        <label>
          Action
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            {catalog.actions.map((a) => (
              <option key={a.key} value={a.key}>
                {a.verb} {a.resource_type}
              </option>
            ))}
          </select>
        </label>

        {selected && (
          <p className={`cleanup__desc ${selected.destructive ? "is-destructive" : ""}`}>
            {selected.destructive ? "⚠️ Irreversible. " : "↩️ Reversible. "}
            {selected.description}
          </p>
        )}

        {eligible.length > 0 && (
          <label>
            Eligible findings from the last scan
            <select value="" onChange={(e) => e.target.value && pickResource(e.target.value)}>
              <option value="">Choose a finding…</option>
              {eligible.map((r) => (
                <option key={r.resource_id} value={r.resource_id}>
                  {r.name || r.resource_id} · {r.region}
                  {r.account_label ? ` · ${r.account_label}` : ""}
                </option>
              ))}
            </select>
          </label>
        )}

        <div className="cleanup__row">
          <label>
            Resource ID
            <input
              value={resourceId}
              onChange={(e) => setResourceId(e.target.value)}
              placeholder="e.g. i-0abc… / eipalloc-… / vol-…"
            />
          </label>
          <label>
            Region
            <input value={region} onChange={(e) => setRegion(e.target.value)} />
          </label>
        </div>

        <label>
          Type the resource ID again to confirm
          <input
            value={confirmId}
            onChange={(e) => setConfirmId(e.target.value)}
            placeholder="must match exactly"
          />
        </label>

        <label className="cleanup__dry">
          <input
            type="checkbox"
            checked={dryRun || previewOnly}
            disabled={previewOnly}
            onChange={(e) => setDryRun(e.target.checked)}
          />
          Dry run (preview only — does not change anything)
          {previewOnly && <span className="cleanup__audit-dry">locked in this build</span>}
        </label>

        <button
          type="submit"
          className={dryRun || previewOnly ? "cleanup__btn" : "cleanup__btn cleanup__btn--live"}
          disabled={busy || !confirmOk || (!catalog.enabled && !previewOnly)}
        >
          {busy ? "Working…" : dryRun || previewOnly ? "Preview cleanup" : "Execute cleanup"}
        </button>
        {!confirmOk && confirmId !== "" && (
          <span className="cleanup__hint">Confirmation must match the resource ID exactly.</span>
        )}
      </form>

      {error && <div className="cleanup__result is-error">{error}</div>}
      {result && (
        <div className={`cleanup__result is-${result.status}`}>
          <strong>{result.status}</strong> — {result.detail}
        </div>
      )}

      {audit.length > 0 && (
        <div className="cleanup__audit">
          <h3>Recent attempts</h3>
          <ul>
            {audit.map((e) => (
              <li key={e.id}>
                <span className={`cleanup__status cleanup__status--${e.status}`}>{e.status}</span>
                <span className="cleanup__audit-action">
                  {e.action} {e.resource_id}
                </span>
                {e.dry_run && <span className="cleanup__audit-dry">dry-run</span>}
                <span className="cleanup__audit-time">
                  {new Date(e.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
