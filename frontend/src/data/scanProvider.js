// Single place the app resolves its data source.
//
// The demo build sets VITE_DEMO_MODE=true, which swaps in fixture data. This is
// a *build-time* selection, so the public demo bundle never contains the API
// client's endpoints at all. Security does not rest on this flag either way:
// the demo is deployed as static files with no network path to the private API.
import { apiScanProvider } from "./apiScanProvider.js";
import { demoScanProvider } from "./demoScanProvider.js";

export const isDemoMode = import.meta.env.VITE_DEMO_MODE === "true";

export const scanProvider = isDemoMode ? demoScanProvider : apiScanProvider;

// Convenience re-export so components can ask "may I offer this?" rather than
// "am I in demo mode?".
export const capabilities = scanProvider.capabilities;
