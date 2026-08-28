# Frontend

Everything about `frontend/` - how it's structured, how to run it in dev,
and how it gets served in dev vs production. For getting the app running at
all, see the [README](../README.md) quickstart first.

## React + Redux Toolkit

All post-login pages — `/home`, `/app` (the recorder), `/admin`,
`/translate`, `/recordings` (a user's own recordings, formerly a slide-out
drawer over `/app`) and `/upload` (the batch transcribe form, formerly a
`?upload=1` panel over `/app` or `/admin`) — are migrated off vanilla JS,
completing a staged migration (`/home` → recorder → admin → translate)
tracked in scratch notes no longer in the repo. All six are client-side
routes of one SPA in
`frontend/` (Vite + React + TypeScript + Redux Toolkit/RTK Query) —
react-router decides what renders (and gates `/admin` to admins
client-side via `RequireAuth`'s `adminOnly` prop).

`frontend/` is the single source directory for **every** frontend file in
the repo, including the handful that aren't part of the React bundle:
`frontend/public/login.html` (pre-auth sign-in page, deliberately kept
vanilla — no reason to migrate), `theme.css` and `theme-preboot.js` (shared
dark-mode styling/boot, linked by `frontend/index.html`), and
`pcm-worklet.js` (the recorder/translate mic-capture AudioWorklet, loaded
by raw URL rather than bundled — a browser requirement for worklet
modules). Vite's `public/` dir copies these verbatim into `frontend/dist/`
on every build, same as the rest of the bundle — no separate copy step,
no second directory. There is no `voice_transcriber/static/` any more.

*Who actually serves `frontend/dist/` differs between dev and production*:
`server.py` (`config.FRONTEND_DIST_DIR`, gated by its `SERVE_FRONTEND`
check) serves straight out of it in dev — `/`, `/login`, and the
`/static/*` mount all read from it directly, and so do `/home`, `/app`,
`/admin`, `/translate`, `/recordings` and `/upload` (all serving
`frontend/dist/index.html`, the SPA shell). In production
(`docker-compose.prod.yml`), a separate `frontend` container (nginx,
`frontend/Dockerfile` + `frontend/nginx.conf`) serves the exact same set of
routes from its own copy of `frontend/dist/` instead — the backend image
never contains it there, so `SERVE_FRONTEND` is false and those routes
simply don't register on `web`. See [DEPLOYMENT.md](../DEPLOYMENT.md) for
the full production
topology.

The old vanilla `home.html`/`index.html`/`admin.html`/`translate.html` and
the shared scripts they used
(`header.js`/`sidebar.js`/`theme-toggle.js`/`upload.js`/`recorder-turns.js`/
`translate-views.js`) were kept as a rollback path through the migration
and have since been deleted, now that the SPA is confirmed stable — restore
them from git history (`git log -- voice_transcriber/static/`) if ever
needed.

Dev — two ways to run the frontend, pick based on whether you're actively
editing it:

**Build-and-serve** (no hot-reload, simplest — good for a quick check or
when you're not touching frontend code):

```bash
npm --prefix frontend install   # first time only
npm --prefix frontend run build
uvicorn voice_transcriber.server:app --reload --port 8000
```

Open http://localhost:8000/home (or `/app`, `/admin`, `/translate`,
`/recordings`, `/upload`, or `/login`). This writes everything the backend
needs straight to `frontend/dist/` — the SPA shell, its hashed assets, and
(via Vite's public-dir copy) `login.html`, `theme.css`, `theme-preboot.js`
and `pcm-worklet.js`. In Docker, the equivalent is the Dockerfile's
`backend-with-frontend` target (what `docker-compose.yml` uses), which
copies `frontend/dist/` from its own build stage into the image at the same
path; the default `backend` target (what production uses instead) skips
that copy entirely — see the Dockerfile's own header comment. After any
frontend change, rerun `npm --prefix frontend run build` and refresh the
browser — there's no hot-reload on this path.

**Vite dev server** (hot-reload — recommended while actively iterating on
`frontend/`): a real `vite` dev server on `:8000` proxies `/api`,
`/healthz`, `/ws`, `/ws/translate`, and the two vanilla pages (`/` and
`/login`) to the backend, which runs separately on `:3000`:

```bash
npm --prefix frontend install   # first time only

# terminal 1
uvicorn voice_transcriber.server:app --port 3000

# terminal 2
npm --prefix frontend run dev
```

Open http://localhost:8000/home (or `/app`, `/admin`, `/translate`,
`/recordings`, `/upload`, or `/login`) — same routes as above, but edits to
`frontend/src/` now hot-reload without a rebuild. The proxy (defined in
`frontend/vite.config.ts`) is what keeps the browser effectively
same-origin in dev, so code that reads `window.location` (`baseApi.ts`,
`useRecorderConnection.ts`, `useTranslateConnection.ts`) works unchanged.
Both ports are read from `FRONTEND_PORT`/`BACKEND_PORT` env vars if you ever
need to change them (defaulting to 8000/3000, matching this convention).

For requests that hit the backend's `:3000` directly instead of going
through the Vite proxy (e.g. testing the API with curl), a dev-only CORS
policy in `server.py` allows the origin in `DEV_FRONTEND_ORIGIN`
(`voice_transcriber/config.py`, default `http://localhost:8000`) — gated off
entirely when `config.PRODUCTION` is true, so it adds no CORS surface in
production (which stays single-origin behind nginx, unaffected by any of
this).

This dev split only affects local development — `docker-compose.yml`'s
`web` service defaults to `:3000` to match, paired with either running `npm
--prefix frontend run dev` on the host at `:8000` (above), or the
containerized equivalent: `docker-compose.yml`'s own `frontend` service
(`frontend/Dockerfile`'s `dev` target), which runs the same Vite dev server
in its own container - `docker compose up -d` brings up `db`, `redis`,
`migrate`, `web`, and `frontend` together, no host-side `npm`/`uvicorn`
needed at all. `frontend/` is bind-mounted for live-reload; a separate
anonymous volume keeps `node_modules` from being shadowed by that mount
(esbuild/Rollup ship platform-specific native binaries, so the container's
own Linux `npm ci` has to win, not whatever - or nothing - is on the host).
Editing on a host path that's bind-mounted into a container can miss native
file-change events depending on your OS/Docker Desktop version, so this
service sets `WATCH_POLL=1` (see `vite.config.ts`) to poll for changes
instead - the bare-host workflow above doesn't need this and keeps
instant, zero-CPU-cost native events.

`docker-compose.prod.yml` and the Dockerfile are unchanged: production
still builds `frontend/dist/` once, but serves it from the separate
`nginx` container (not the backend process), never a Vite dev server - see
[DEPLOYMENT.md](../DEPLOYMENT.md). `web` (dev) still also bakes `frontend/dist/`
into its own image (`backend-with-frontend` target) alongside `frontend`'s
hot-reload container - a narrower, distinct need: `/` and `/login` are
proxied to `web`, which serves them from a physical `frontend/dist/login.html`
(a backend-owned vanilla page, not part of the React app `frontend`
hot-reloads) - see that target's own comment in the Dockerfile.

Frontend tests:

```bash
npm --prefix frontend run test
```

Formatting (Prettier; not enforced in CI yet, run before committing):

```bash
npm --prefix frontend run format        # rewrite in place
npm --prefix frontend run format:check  # CI-style check, no writes
```

There's deliberately no `lint` script yet: `typescript-eslint` doesn't
support TypeScript 7 (this project's compiler) as of this writing - it
hard-errors on import rather than degrading gracefully. Revisit once
[their TS 7 support lands](https://github.com/typescript-eslint/typescript-eslint/issues/10940);
`tsc -b`'s own `strict`/`noUnusedLocals`/`noUnusedParameters` in the
meantime catch a meaningful chunk of what a linter would.

## Source layout (Feature-Sliced Design)

`frontend/src/` follows [Feature-Sliced Design](https://feature-sliced.design/):
higher layers may import from lower ones, never the reverse.

```
app/       Redux store + typed hooks (store.ts, hooks.ts)
pages/     Route-level compositions - home, recorder, admin, translate,
           recordings, upload. Each is <page>/ui/ holding that page's own
           component tree (nothing in here is imported by any other slice)
widgets/   Composite UI used across multiple pages: app-layout, header, sidebar
features/  User-facing interactions with their own state: auth, recorder,
           translate, transcribe (upload), theme
entities/  Fetched domain data + its API: recording, user, language, speaker
shared/    Business-agnostic code: api/baseApi.ts (RTK Query base),
           lib/ (pure formatting/parsing helpers - fmtDate, initials, etc.)
```

Within a slice, code is grouped by segment: `ui/` (components), `model/`
(state, types, hooks), `api/` (RTK Query endpoints), `lib/` (pure helpers
scoped to that slice). Tests are colocated as `Foo.test.tsx` next to `Foo.tsx`
throughout - the one test-file convention used everywhere, rather than a mix
of colocated files and `__tests__/` folders.

Cross-slice imports use the `@/` alias (e.g. `@/entities/user/api/usersApi`),
configured in `tsconfig.app.json`, `vite.config.ts` and `vitest.config.ts` -
so import paths don't depend on how deeply nested the importing file is.
`main.tsx`, `index.css`, `setupTests.ts` and `mocks/` (MSW test handlers)
sit outside the layer system, same as any FSD app's entry point and test
infra.

## VS Code performance (optional)

`.vscode/` is gitignored, so editor settings aren't shared automatically. If
VS Code feels sluggish (large `.venv`/`node_modules`/`__pycache__` trees), add
this to your own `.vscode/settings.json` to stop the file watcher and search
indexer from scanning them:

```json
{
  "files.exclude": {
    "**/.git": true,
    "**/__pycache__": true,
    "**/*.pyc": true,
    "**/.venv": true,
    "**/venv": true,
    "**/node_modules": true,
    "frontend/dist": true,
    "**/.pytest_cache": true
  },
  "files.watcherExclude": {
    "**/.venv/**": true,
    "**/venv/**": true,
    "**/__pycache__/**": true,
    "**/*.pyc": true,
    "**/node_modules/**": true,
    "frontend/dist/**": true
  },
  "search.exclude": {
    "**/.venv": true,
    "**/venv": true,
    "**/__pycache__": true,
    "**/node_modules": true,
    "frontend/dist": true
  }
}
```

Note: `code --status` (Workspace Stats) does not respect these settings — it's a raw
diagnostic scan of the folder tree, not an editor-state report. Check the Explorer
sidebar or Search panel to confirm `.venv` is actually excluded.

This only affects the editor (watching/search/Explorer display); it has no
effect on how the app runs.
