import { useEffect, useRef, useState } from "react";
import AccountsPanel from "../components/AccountsPanel.jsx";
import AlertsPanel from "../components/AlertsPanel.jsx";
import BillingPanel from "../components/BillingPanel.jsx";
import CleanupPanel from "../components/CleanupPanel.jsx";
import CompareBar from "../components/CompareBar.jsx";
import DiffView from "../components/DiffView.jsx";
import RegionFailures from "../components/RegionFailures.jsx";
import ResourceTable from "../components/ResourceTable.jsx";
import ScanHistory from "../components/ScanHistory.jsx";
import ScanProgress from "../components/ScanProgress.jsx";
import ThemeToggle from "../components/ThemeToggle.jsx";
import UsersPanel from "../components/UsersPanel.jsx";
import { capabilities, isDemoMode, scanProvider } from "../data/scanProvider.js";

const RISK_ORDER = { HIGH: 0, REVIEW: 1, MEDIUM: 2, LOW: 3 };

function sortByRisk(resources) {
  return [...resources].sort((a, b) => RISK_ORDER[a.risk_level] - RISK_ORDER[b.risk_level]);
}

export default function Dashboard() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [summary, setSummary] = useState(null);
  const [resources, setResources] = useState([]);
  const [alerts, setAlerts] = useState([]);
  // Regions this scan could not read. Live scans only — a saved scan does not
  // record them, so viewing history clears it rather than showing a stale one.
  const [regionsFailed, setRegionsFailed] = useState([]);
  const [hasScanned, setHasScanned] = useState(false);

  // The progress bar outlives `loading` by one completion beat, so it can fill
  // to 100% instead of vanishing mid-fill.
  const [progress, setProgress] = useState(null); // null | {done, reveal}

  // Top of the results region; a finished scan scrolls here.
  const resultsRef = useRef(null);
  const diffRef = useRef(null);

  // Team. `me` is the current principal; `users = null` hides the panel.
  const [me, setMe] = useState(null);
  const [users, setUsers] = useState(null);

  // Per-account filter for the resource table ("all" or an account_label).
  const [accountFilter, setAccountFilter] = useState("all");

  // Multi-account. `accounts = null` means persistence is disabled.
  const [accounts, setAccounts] = useState(null);

  // Persistence / history. `scans = null` means persistence is disabled.
  const [scans, setScans] = useState(null);
  const [activeScanId, setActiveScanId] = useState(null); // null => viewing live
  const [viewingMeta, setViewingMeta] = useState(null); // {created_at} when viewing a saved scan

  // Compare / diff state.
  const [compareFrom, setCompareFrom] = useState("");
  const [compareTo, setCompareTo] = useState("");
  const [diff, setDiff] = useState(null);
  const [comparing, setComparing] = useState(false);

  async function refreshHistory() {
    try {
      const data = await scanProvider.listScans();
      setScans(data.scans);
      return data.scans;
    } catch {
      // 503 (persistence disabled) or backend down — just hide the panel.
      setScans(null);
      return null;
    }
  }

  async function refreshAccounts() {
    try {
      const data = await scanProvider.listAccounts();
      setAccounts(data.accounts);
    } catch {
      setAccounts(null); // persistence disabled — hide the panel
    }
  }

  async function addAccount(account) {
    await scanProvider.createAccount(account);
    refreshAccounts();
  }

  async function removeAccount(accountId) {
    await scanProvider.deleteAccount(accountId);
    refreshAccounts();
  }

  async function refreshUsers() {
    if (!capabilities.team) {
      setUsers(null); // the demo has no team management
      return;
    }
    try {
      const data = await scanProvider.listUsers();
      setUsers(data.users);
    } catch {
      setUsers(null); // persistence disabled — hide the panel
    }
  }

  async function addUser(user) {
    const created = await scanProvider.createUser(user);
    refreshUsers();
    return created; // contains the one-time api_key
  }

  async function removeUser(userId) {
    await scanProvider.deleteUser(userId);
    refreshUsers();
  }

  useEffect(() => {
    scanProvider
      .getMe()
      .then(setMe)
      .catch(() => setMe(null));
    refreshHistory();
    refreshAccounts();
    refreshUsers();

    // The demo populates itself. A visitor should never meet an empty
    // dashboard wondering what this is — the findings are the pitch. Live
    // builds still wait for an explicit scan, because scanning a real account
    // is not something to do to someone unasked.
    if (!capabilities.liveScan) runScan({ revealResults: false });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Default the compare selectors to (older, newest) once history loads.
  useEffect(() => {
    if (scans && scans.length >= 2) {
      if (!compareTo) setCompareTo(scans[0].scan_id);
      if (!compareFrom) setCompareFrom(scans[1].scan_id);
    }
  }, [scans]); // eslint-disable-line react-hooks/exhaustive-deps

  async function runCompare() {
    setComparing(true);
    setError(null);
    try {
      const result = await scanProvider.compareScans(compareFrom, compareTo);
      setDiff(result);
      // The diff replaces the results area, which now sits above this control.
      scrollTo(diffRef);
    } catch (e) {
      setError(e.message);
    } finally {
      setComparing(false);
    }
  }

  function scrollTo(ref) {
    requestAnimationFrame(() =>
      ref.current?.scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "auto"
          : "smooth",
        block: "start",
      })
    );
  }

  async function runScan({ revealResults = true } = {}) {
    setLoading(true);
    setError(null);
    setProgress({ done: false, reveal: revealResults });
    try {
      const data = await scanProvider.runScan();
      setResources(sortByRisk(data.resources));
      setSummary(data.summary);
      setAlerts(data.alerts || []);
      setRegionsFailed(data.regions_failed || []);
      setHasScanned(true);
      setActiveScanId(null);
      setViewingMeta(null);
      refreshHistory(); // a saved scan may have just been added
      // Let the bar finish; the reveal happens when it dismisses itself.
      setProgress((p) => (p ? { ...p, done: true } : p));
    } catch (e) {
      // The demo has no API, so pointing a visitor at one would be nonsense —
      // and would leak a localhost URL into the public bundle.
      setError(
        isDemoMode
          ? `${e.message}. The demo runs on bundled sample data; try reloading the page.`
          : `${e.message}. Is the API reachable at ${
              import.meta.env.VITE_API_BASE_URL || "the configured base URL"
            }, and are its AWS credentials configured?`
      );
      // Drop the bar immediately on failure — the error banner is the message,
      // and a bar animating to "complete" would contradict it.
      setProgress(null);
    } finally {
      setLoading(false);
    }
  }

  async function loadSavedScan(scanId) {
    setLoading(true);
    setError(null);
    try {
      const record = await scanProvider.getScan(scanId);
      setResources(sortByRisk(record.resources));
      setSummary(record.summary);
      setAlerts([]); // alerts reflect the latest live scan, not a historical view
      setRegionsFailed([]); // not recorded with a saved scan
      setHasScanned(true);
      setActiveScanId(scanId);
      setViewingMeta({ created_at: record.created_at });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  const viewingLive = activeScanId === null;
  const isAdmin = me?.role === "admin";

  // Per-account filtering for the resource table.
  const accountLabels = [
    ...new Set(resources.map((r) => r.account_label).filter(Boolean)),
  ];
  const filteredResources =
    accountFilter === "all"
      ? resources
      : resources.filter((r) => r.account_label === accountFilter);

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Shut It Down</h1>
          <p className="subtitle">
            Find AWS lab resources that may still be costing you money.
          </p>
        </div>
        <div className="page__header-actions">
          <ThemeToggle />
          <button className="scan-button" onClick={() => runScan()} disabled={loading}>
            {loading ? "Scanning…" : "Run scan"}
          </button>
        </div>
      </header>

      {isDemoMode ? (
        <div className="notice notice--demo">
          🧪 <strong>Demo mode</strong> — every figure below is representative sample data.
          This build makes no AWS calls and holds no credentials. The scanners, cross-account
          STS access, and cleanup safeguards are real; see the source and the sandbox
          walkthrough.
        </div>
      ) : (
        <div className="notice">
          🔒 Scanning is strictly read-only — it only issues Describe/List/Get calls and
          never modifies your account. Guided cleanup is a separate, opt-in feature that is
          disabled by default and requires explicit per-resource confirmation.
        </div>
      )}

      {progress && (
        <ScanProgress
          done={progress.done}
          onDone={() => {
            const shouldReveal = progress.reveal;
            setProgress(null);
            if (shouldReveal) scrollTo(resultsRef);
          }}
        />
      )}

      {error && <div className="error">{error}</div>}

      {/* Scroll target for a completed scan — the top of the results region. */}
      <div ref={resultsRef} />

      {/* Above the summary tiles on purpose: "these totals are incomplete" has
          to be read before the totals are. */}
      {viewingLive && <RegionFailures failures={regionsFailed} />}

      {viewingLive && <AlertsPanel alerts={alerts} />}

      {!viewingLive && viewingMeta && (
        <div className="banner">
          📜 Viewing a saved scan from{" "}
          <strong>{new Date(viewingMeta.created_at).toLocaleString()}</strong>. Click
          <button className="banner__link" onClick={() => runScan()}>
            Run scan
          </button>
          for a fresh one.
        </div>
      )}

      <div className={scans !== null ? "layout layout--with-history" : "layout"}>
        <main className="layout__main">
          {diff ? (
            <div ref={diffRef}>
              <DiffView diff={diff} onClose={() => setDiff(null)} />
            </div>
          ) : (
            <>
              {summary && (
                <div className="summary">
                  {summary.estimated_monthly_cost !== undefined && (
                    <SummaryCard
                      label="Est. $/mo"
                      value={`$${Number(summary.estimated_monthly_cost).toFixed(2)}`}
                    />
                  )}
                  <SummaryCard label="Total resources" value={summary.total_resources} />
                  <SummaryCard label="High" value={summary.by_risk_level?.HIGH || 0} tone="HIGH" />
                  <SummaryCard
                    label="Review"
                    value={summary.by_risk_level?.REVIEW || 0}
                    tone="REVIEW"
                  />
                  <SummaryCard
                    label="Medium"
                    value={summary.by_risk_level?.MEDIUM || 0}
                    tone="MEDIUM"
                  />
                  <SummaryCard label="Low" value={summary.by_risk_level?.LOW || 0} tone="LOW" />
                </div>
              )}

              {hasScanned && accountLabels.length > 1 && (
                <div className="account-filter">
                  <label>
                    Account view:{" "}
                    <select
                      value={accountFilter}
                      onChange={(e) => setAccountFilter(e.target.value)}
                    >
                      <option value="all">All accounts ({resources.length})</option>
                      {accountLabels.map((label) => (
                        <option key={label} value={label}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              )}

              {hasScanned ? (
                <ResourceTable resources={filteredResources} />
              ) : (
                <p className="empty">Click “Run scan” to inspect your AWS account.</p>
              )}
            </>
          )}
        </main>

        {scans !== null && (
          <ScanHistory
            scans={scans}
            activeId={activeScanId}
            onSelect={loadSavedScan}
            onLive={runScan}
            viewingLive={viewingLive}
          />
        )}
      </div>

      {/* Comparison sits *below* the findings. Above them it read as a filter
          governing what you were looking at — visitors thought they were being
          shown an old scan. It is a secondary, historical action. */}
      {scans !== null && scans.length >= 2 && (
        <CompareBar
          scans={scans}
          fromId={compareFrom}
          toId={compareTo}
          onChangeFrom={setCompareFrom}
          onChangeTo={setCompareTo}
          onCompare={runCompare}
          busy={comparing}
        />
      )}

      {/* Configuration panels sit below the findings: a visitor should see what the
          scan found before meeting any account, team, or cleanup controls. */}
      {capabilities.billing && <BillingPanel isAdmin={isAdmin} />}

      {users !== null && (
        <UsersPanel
          users={users}
          isAdmin={isAdmin}
          currentUserId={me?.user_id}
          onAdd={addUser}
          onDelete={removeUser}
        />
      )}

      {accounts !== null && (
        <AccountsPanel
          accounts={accounts}
          isAdmin={isAdmin && capabilities.accountsAdmin}
          onAdd={addAccount}
          onDelete={removeAccount}
        />
      )}

      {/* Findings are passed in so an operator can pick an eligible resource
          rather than transcribing an id by hand. */}
      <CleanupPanel isAdmin={isAdmin} resources={resources} />
    </div>
  );
}

function SummaryCard({ label, value, tone }) {
  const toneClass = tone ? ` summary-card--${tone.toLowerCase()}` : "";
  return (
    <div className={`summary-card${toneClass}`}>
      <div className="summary-card__value">{value}</div>
      <div className="summary-card__label">{label}</div>
    </div>
  );
}
