import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server runs on 5173 (the default the backend CORS config allows).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});
