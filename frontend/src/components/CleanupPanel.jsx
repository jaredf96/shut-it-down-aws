import { useEffect, useState } from "react";
import { scanProvider } from "../data/scanProvider.js";

// Guided, auditable cleanup. Admin-only. Designed as a careful checklist:
// pick an action, type the exact resource id to confirm, dry-run first.
export default function CleanupPanel({ isAdmin }) {
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

  if (!isAdmin || catalog === null) return null;

  const selected = catalog.actions.find((a) => a.key === action);
  const confirmOk = resourceId.trim() !== "" && resourceId.trim() === confirmId.trim();

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
        dry_run: dryRun,
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
        <span className={`cleanup__flag ${catalog.enabled ? "is-on" : "is-off"}`}>
          {catalog.enabled ? "enabled" : "disabled in this environment"}
        </span>
      </div>

      {!catalog.enabled && (
        <p className="cleanup__note">
          Mutating actions are off. Set <code>ENABLE_CLEANUP_ACTIONS=true</code> on the
          backend to enable them. You can still review the supported actions below.
        </p>
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
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
          Dry run (preview only — does not change anything)
        </label>

        <button
          type="submit"
          className={dryRun ? "cleanup__btn" : "cleanup__btn cleanup__btn--live"}
          disabled={busy || !confirmOk || !catalog.enabled}
        >
          {busy ? "Working…" : dryRun ? "Preview" : "Execute cleanup"}
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
