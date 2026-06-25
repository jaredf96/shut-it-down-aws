import { useState } from "react";

// Team members of the tenant. Admins can add/remove; members see a read-only
// roster. A newly created member's API key is shown once.
export default function UsersPanel({ users, isAdmin, currentUserId, onAdd, onDelete }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [role, setRole] = useState("member");
  const [newKey, setNewKey] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await onAdd({ name: name.trim(), role });
      setNewKey({ name: created.name, api_key: created.api_key });
      setName("");
      setRole("member");
      setOpen(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="users">
      <div className="users__header">
        <h2>Team ({users.length})</h2>
        {isAdmin && (
          <button className="users__toggle" onClick={() => setOpen((o) => !o)}>
            {open ? "Cancel" : "+ Add member"}
          </button>
        )}
      </div>

      {newKey && (
        <div className="users__key">
          API key for <strong>{newKey.name}</strong> (copy now — shown once):
          <code>{newKey.api_key}</code>
          <button onClick={() => setNewKey(null)}>Dismiss</button>
        </div>
      )}

      <ul className="users__list">
        {users.map((u) => (
          <li key={u.user_id} className="users__item">
            <div>
              <span className="users__name">{u.name}</span>
              <span className={`users__role users__role--${u.role}`}>{u.role}</span>
              {u.user_id === currentUserId && <span className="users__you">you</span>}
            </div>
            {isAdmin && u.user_id !== currentUserId && (
              <button className="users__delete" onClick={() => onDelete(u.user_id)}>
                Remove
              </button>
            )}
          </li>
        ))}
      </ul>

      {open && isAdmin && (
        <form className="users__form" onSubmit={submit}>
          <input
            placeholder="Member name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="member">member</option>
            <option value="admin">admin</option>
          </select>
          <button type="submit" disabled={busy}>
            {busy ? "Adding…" : "Add"}
          </button>
          {error && <span className="users__error">{error}</span>}
        </form>
      )}
    </section>
  );
}
