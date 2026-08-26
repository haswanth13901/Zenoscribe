import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: `vite` (this file) serves the app on FRONTEND_PORT and proxies
// API/WS calls to the backend uvicorn process on BACKEND_HOST:BACKEND_PORT
// (see README/DEPLOYMENT.md's two-terminal dev workflow) - the proxy is
// what keeps the browser effectively same-origin in dev, so
// window.location.origin (baseApi.ts) and window.location.host
// (useRecorderConnection.ts, useTranslateConnection.ts) resolve correctly
// without any dev-only branching in that code. All three default to this
// repo's convention (frontend 8000, backend host `localhost`, port 3000)
// but are read from the environment rather than repeated as literals
// below, so there is exactly one place each is defined - override with
// FRONTEND_PORT/BACKEND_HOST/BACKEND_PORT env vars if you ever need to.
// BACKEND_HOST is what lets this same config run either paired with a bare
// `uvicorn` process on the host (the default, "localhost") or containerized
// in docker-compose.yml's `frontend` service, which sets it to "web" - the
// Compose service name - so the proxy resolves inside the container network
// instead of trying (and failing) to reach the frontend container's own
// loopback interface.
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
const BACKEND_HOST = process.env.BACKEND_HOST || "localhost";
const BACKEND_PORT = Number(process.env.BACKEND_PORT) || 3000;
const backendTarget = `http://${BACKEND_HOST}:${BACKEND_PORT}`;

export default defineConfig(({ command }) => ({
  plugins: [
    react(),
    // login.html (a public/ file, served byte-for-byte in both dev and
    // prod - see server.py's login_page()) hardcodes its asset paths under
    // "/static/" to match production, where that prefix is mounted at the
    // dist root (NoCacheStaticFiles in server.py / the /static/ location in
    // nginx.conf). The dev server has no such mount - public/ files are
    // served straight off "/" (base above) - so without this, every
    // "/static/..." reference in login.html (login.js itself included) 404s
    // and e.g. the sign-in button silently gets no click handler. Stripping
    // the prefix here before Vite's own static/publicDir middleware runs
    // reproduces the production mount in dev, for every "/static/" request,
    // not just login.js.
    {
      name: "dev-static-prefix-passthrough",
      configureServer(server) {
        server.middlewares.use((req, _res, next) => {
          if (req.url?.startsWith("/static/")) {
            req.url = req.url.slice("/static".length);
          }
          next();
        });
      },
    },
  ],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  base: command === "build" ? "/static/" : "/",
  server: {
    port: FRONTEND_PORT,
    strictPort: true,
    // Polling, not native fs events, when running in Docker (WATCH_POLL=1,
    // set by docker-compose.yml's `frontend` service only): a bind mount of
    // a Windows/macOS host path into a Linux container doesn't reliably
    // propagate the host's native file-change notifications through
    // Docker Desktop's virtualization layer, so Vite's default watcher can
    // sit indefinitely without seeing an edit - confirmed directly (an
    // edited file produced zero HMR log output). The bare-host workflow
    // (README's two-terminal setup) doesn't set this and keeps native
    // events, which are instant and don't burn CPU polling.
    watch: process.env.WATCH_POLL ? { usePolling: true, interval: 300 } : undefined,
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
