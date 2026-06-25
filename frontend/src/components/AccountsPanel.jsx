import { useState } from "react";

// Manage the AWS accounts scanned for this tenant. Only rendered when the
// backend has persistence enabled (accounts require it).
export default function AccountsPanel({ accounts, isAdmin = true, onAdd, onDelete }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [roleArn, setRoleArn] = useState("");
  const [externalId, setExternalId] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onAdd({
        name: name.trim(),
        role_arn: roleArn.trim(),
        external_id: externalId.trim() || null,
      });
      setName("");
      setRoleArn("");
      setExternalId("");
      setOpen(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="accounts">
      <div className="accounts__header">
        <h2>AWS accounts ({accounts.length})</h2>
        {isAdmin && (
          <button className="accounts__toggle" onClick={() => setOpen((o) => !o)}>
            {open ? "Cancel" : "+ Add account"}
          </button>
        )}
      </div>

      {accounts.length === 0 && !open && (
        <p className="accounts__empty">
          No accounts registered — scans use the server's own credentials. Add an
          account to scan it via cross-account role.
        </p>
      )}

      {accounts.length > 0 && (
        <ul className="accounts__list">
          {accounts.map((a) => (
            <li key={a.account_id} className="accounts__item">
              <div>
                <span className="accounts__name">{a.name}</span>
                <span className="accounts__id">{a.account_id}</span>
                <span className="accounts__arn">{a.role_arn}</span>
              </div>
              {isAdmin && (
                <button className="accounts__delete" onClick={() => onDelete(a.account_id)}>
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {open && (
        <form className="accounts__form" onSubmit={submit}>
          <input
            placeholder="Display name (e.g. Sandbox)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <input
            placeholder="Role ARN (arn:aws:iam::123456789012:role/…)"
            value={roleArn}
            onChange={(e) => setRoleArn(e.target.value)}
            required
          />
          <input
            placeholder="External ID (optional)"
            value={externalId}
            onChange={(e) => setExternalId(e.target.value)}
          />
          <button type="submit" disabled={busy}>
            {busy ? "Adding…" : "Add"}
          </button>
          {error && <span className="accounts__error">{error}</span>}
        </form>
      )}
    </section>
  );
}
