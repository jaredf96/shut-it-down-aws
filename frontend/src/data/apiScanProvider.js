// Provider backed by the real HTTP API. This is the only module in the app
// that is allowed to talk to `api/client.js`; every component goes through the
// provider interface instead, so the demo build can swap in fixtures without
// any `if (demoMode)` checks scattered through the component tree.
import {
  createAccount,
  createUser,
  deleteAccount,
  deleteUser,
  executeCleanup,
  getBilling,
  getCleanupActions,
  getCleanupAudit,
  getDiff,
  getMe,
  getScan,
  listAccounts,
  listScans,
  listUsers,
  scanAll,
  setPlan,
  startCheckout,
} from "../api/client.js";

/** @type {import("./contract").ScanProvider} */
export const apiScanProvider = {
  mode: "api",

  // What the surrounding UI is allowed to offer. The live app can do
  // everything; the backend still enforces its own gates independently.
  capabilities: {
    liveScan: true,
    history: true,
    accountsAdmin: true,
    team: true,
    billing: true,
    cleanupExecute: true,
  },

  // --- Scans ---
  runScan: () => scanAll(),
  listScans: (limit) => listScans(limit),
  getScan: (scanId) => getScan(scanId),
  compareScans: (fromId, toId) => getDiff(fromId, toId),

  // --- Accounts ---
  listAccounts: () => listAccounts(),
  createAccount: (account) => createAccount(account),
  deleteAccount: (accountId) => deleteAccount(accountId),

  // --- Team ---
  getMe: () => getMe(),
  listUsers: () => listUsers(),
  createUser: (user) => createUser(user),
  deleteUser: (userId) => deleteUser(userId),

  // --- Billing ---
  getBilling: () => getBilling(),
  setPlan: (plan) => setPlan(plan),
  startCheckout: () => startCheckout(),

  // --- Cleanup ---
  getCleanupActions: () => getCleanupActions(),
  getCleanupAudit: (limit) => getCleanupAudit(limit),
  executeCleanup: (request) => executeCleanup(request),
};
