import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Fixtures live at repo root (../demo-data) so the backend test suite can
// validate them against the real Pydantic models — see the fixture schema test.
const demoDataDir = fileURLToPath(new URL("../demo-data", import.meta.url));

// Dev server runs on 5173 (the default the backend CORS config allows).
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@demo-data": demoDataDir,
    },
  },
  server: {
    port: 5173,
    fs: {
      // Allow serving the fixture directory, which sits outside the Vite root.
      allow: [".."],
    },
  },
});
