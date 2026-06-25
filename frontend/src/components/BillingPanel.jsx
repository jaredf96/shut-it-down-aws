import { useEffect, useState } from "react";
import { getBilling, setPlan, startCheckout } from "../api/client.js";

// Plan, usage, and upgrade. Admin-only. When Stripe is configured, upgrading
// opens Checkout; otherwise (dev) an admin can switch plans directly.
export default function BillingPanel({ isAdmin }) {
  const [billing, setBilling] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setBilling(await getBilling());
    } catch {
      setBilling(null);
    }
  }

  useEffect(() => {
    load();
  }, []);

  if (!isAdmin || billing === null) return null;

  const { plan, limits, usage, plans, billing_managed_by_stripe } = billing;
  const atAccountLimit = usage.accounts >= limits.max_accounts;

  async function upgrade() {
    setBusy(true);
    setError(null);
    try {
      const { url } = await startCheckout();
      window.location.href = url;
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function choosePlan(next) {
    setBusy(true);
    setError(null);
    try {
      await setPlan(next);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="billing">
      <div className="billing__header">
        <h2>Plan & usage</h2>
        <span className={`billing__plan billing__plan--${plan}`}>{limits.label}</span>
      </div>

      <div className="billing__usage">
        <span className={atAccountLimit ? "is-limit" : ""}>
          AWS accounts: {usage.accounts} / {limits.max_accounts}
        </span>
        <span>
          Team members: {usage.users} / {limits.max_users}
        </span>
      </div>

      {billing_managed_by_stripe ? (
        plan !== "pro" && (
          <button className="billing__upgrade" onClick={upgrade} disabled={busy}>
            {busy ? "Redirecting…" : "Upgrade to Pro"}
          </button>
        )
      ) : (
        <div className="billing__dev">
          <span>Dev mode (no Stripe) — set plan:</span>
          {Object.keys(plans).map((key) => (
            <button
              key={key}
              className={`billing__chip ${key === plan ? "is-active" : ""}`}
              onClick={() => choosePlan(key)}
              disabled={busy}
            >
              {plans[key].label}
            </button>
          ))}
        </div>
      )}

      {error && <div className="billing__error">{error}</div>}
    </section>
  );
}
