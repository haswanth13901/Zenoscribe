import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev-time backend: FastAPI serves everything this Vite dev server
// doesn't own (auth API, /static assets, and the still-vanilla pages).
// Vite is the single dev-time origin so sessionStorage (origin-scoped)
// written by login.html on :8000 is only ever read back through the same
// origin the browser actually navigates to.
const BACKEND_ORIGIN = "http://localhost:8000";

export default defineConfig(({ command }) => ({
  plugins: [react()],
  // Production build assets are served by FastAPI's existing /static mount,
  // from voice_transcriber/static/spa_dist/ (see server.py's /home, /app,
  // /admin and /translate routes - all client-side routes of this one SPA
  // build).
  base: command === "build" ? "/static/spa_dist/" : "/",
  build: {
    outDir: "dist",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": BACKEND_ORIGIN,
      // Prefix-matches both /ws (recorder) and /ws/translate.
      "/ws": { target: BACKEND_ORIGIN, ws: true },
      "/login": BACKEND_ORIGIN,
      // /app, /admin and /translate are all in-SPA routes now - deliberately
      // NOT proxied, so Vite's own dev server serves them via SPA fallback
      // instead of forwarding to the backend's (also-React) response for
      // the same path.
      "/static": BACKEND_ORIGIN,
    },
  },
}));
