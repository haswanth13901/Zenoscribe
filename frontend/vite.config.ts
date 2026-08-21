import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: `vite` (this file) serves the app on FRONTEND_PORT and proxies
// API/WS calls to the backend uvicorn process on BACKEND_PORT (see
// README/DEPLOYMENT.md's two-terminal dev workflow) - the proxy is what
// keeps the browser effectively same-origin in dev, so
// window.location.origin (baseApi.ts) and window.location.host
// (useRecorderConnection.ts, useTranslateConnection.ts) resolve correctly
// without any dev-only branching in that code. Both ports default to this
// repo's convention (frontend 8000, backend 3000) but are read from the
// environment rather than repeated as literals below, so there is exactly
// one place each is defined - override with FRONTEND_PORT/BACKEND_PORT env
// vars if you ever need to.
//
// Prod: build assets are served by FastAPI's existing /static mount,
// straight from frontend/dist/ (see config.FRONTEND_DIST_DIR and
// server.py's /home, /app, /admin and /translate routes - all client-side
// routes of this one SPA build - plus / and /login for the still-vanilla
// login.html, which lands in dist/ via Vite's public-dir copy below).
//
// `base` therefore has to differ between the two: "/" in dev, so the app
// and its public/ assets (pcm-worklet.js, service-worker.js, manifest,
// icons) resolve at the dev server's own root exactly like they will need
// to be requested in the browser; "/static/" only for the production
// build, unchanged from before.
const FRONTEND_PORT = Number(process.env.FRONTEND_PORT) || 8000;
const BACKEND_PORT = Number(process.env.BACKEND_PORT) || 3000;
const backendTarget = `http://localhost:${BACKEND_PORT}`;

export default defineConfig(({ command }) => ({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  base: command === "build" ? "/static/" : "/",
  server: {
    port: FRONTEND_PORT,
    strictPort: true,
    proxy: {
      // Exact-match regexes (Vite treats a "^"-prefixed key as a RegExp,
      // not a prefix) for the two vanilla, backend-owned pages - "/" and
      // "/login" both serve frontend/public/login.html via server.py, never
      // part of the React app (main.tsx's routes start at /home). A plain
      // "/" prefix rule would match every path - including /home, /api,
      // and Vite's own client/module requests - so it has to be anchored
      // to exactly "/", not "starts with /".
      "^/$": {
        target: backendTarget,
        changeOrigin: true,
      },
      "^/login$": {
        target: backendTarget,
        changeOrigin: true,
      },
      "/api": {
        target: backendTarget,
        changeOrigin: true,
      },
      "/healthz": {
        target: backendTarget,
        changeOrigin: true,
      },
      "/ws": {
        target: backendTarget,
        ws: true,
        changeOrigin: true,
      },
      "/ws/translate": {
        target: backendTarget,
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
}));
