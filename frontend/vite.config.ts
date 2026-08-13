import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  // Build assets are served by FastAPI's existing /static mount, straight
  // from frontend/dist/ (see config.FRONTEND_DIST_DIR and server.py's
  // /home, /app, /admin and /translate routes - all client-side routes of
  // this one SPA build - plus / and /login for the still-vanilla
  // login.html, which lands in dist/ via Vite's public-dir copy below).
  // There is no dev server: everything is served by FastAPI on :8000,
  // built via `npm run build`.
  base: "/static/",
  build: {
    outDir: "dist",
  },
});
