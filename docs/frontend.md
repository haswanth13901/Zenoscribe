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

Formatting (Prettier). This **is** enforced in CI - `format:check` runs as a
blocking step in `ci.yml`'s `frontend-unit` job, which feeds the
`Dev checks passed` aggregator, so a formatting drift fails the PR the same
way `flake8` does on the backend:

```bash
npm --prefix frontend run format        # rewrite in place
npm --prefix frontend run format:check  # exactly what CI runs
```

## Linting (ESLint) - optional, not installed

There is no `lint` script and no ESLint dependency in this project. That's a
deliberate default, not an oversight, and it's reversible in about five
minutes - the steps below are verified against this codebase.

### What you actually gain

Less than you might expect, because two gates already cover most of it:

| Concern | Already covered by |
|---|---|
| Formatting / style drift | Prettier's `format:check`, blocking in CI |
| Unused variables and parameters | `tsc -b` with `noUnusedLocals` / `noUnusedParameters` |
| Type errors, null safety | `tsc -b` with `strict` |

The one gap neither of those can close is **React hooks correctness**, via
`eslint-plugin-react-hooks`:

- `rules-of-hooks` - a hook called conditionally, or inside a loop or a
  nested function. Perfectly well-typed, and wrong.
- `exhaustive-deps` - a `useEffect`/`useCallback`/`useMemo` dependency array
  that omits something the body reads, giving you a stale closure.

TypeScript cannot catch either: both are valid programs, they just don't do
what the author meant. That matters more here than in a typical CRUD
frontend, because `features/recorder/model/useRecorderConnection.ts` and
`features/translate/model/useTranslateConnection.ts` drive WebSocket
lifecycles, `AudioContext` setup and audio worklets from inside hooks. A
stale closure there doesn't throw - it silently keeps a dead socket open or
opens a second one, which is the same class of bug as the double-start race
found in the original code review.

If you're not touching those hooks, the marginal value over `tsc` + Prettier
is genuinely small.

### What blocks the *usual* setup - and why it doesn't block ESLint

The standard React+TS ESLint stack is built on `typescript-eslint`, and that
cannot run here. It declares `typescript: ">=4.8.4 <6.1.0"` while this
project is on `^7.0.2`, so npm won't resolve the tree; forced past that with
`--legacy-peer-deps` it hard-errors on import rather than degrading:

```
typescript-eslint does not support TS 7.0.
    at Object.<anonymous> (node_modules/typescript-eslint/dist/index.js:52:11)
```

This is a rewrite-level gap, not a stale version range: TypeScript 7 is the
Go rewrite, and its package exports `./unstable/*` surfaces instead of the
old JS compiler API `typescript-eslint` is built on. Tracking issue:
[typescript-eslint#10940](https://github.com/typescript-eslint/typescript-eslint/issues/10940),
now scoped to TS >=7.1. Microsoft's documented side-by-side workaround means
pinning `typescript` to 6.0.3 for tooling - i.e. building the frontend with
TS 6, which is a compiler downgrade to satisfy a linter and not worth it.

**But `typescript-eslint` is only needed for type-aware rules.** The hooks
rules work purely on the syntax tree, so swapping in Babel's parser - which
reads TypeScript syntax without ever loading the TypeScript compiler - gets
you the rules that matter, today, on TS 7.

### Installing it

```bash
npm --prefix frontend install --save-dev \
  eslint eslint-plugin-react-hooks \
  @babel/core @babel/eslint-parser \
  @babel/preset-typescript @babel/preset-react
```

Create `frontend/eslint.config.js`:

```js
import babelParser from "@babel/eslint-parser";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      parser: babelParser,
      parserOptions: {
        requireConfigFile: false,
        babelOptions: {
          presets: ["@babel/preset-typescript", "@babel/preset-react"],
          filename: "file.tsx",
        },
      },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
  },
];
```

`requireConfigFile: false` and the inline `filename` matter - without them
Babel looks for a project `babel.config.json` this repo doesn't have, and
can't tell `.ts` from `.tsx`.

Add to `frontend/package.json`:

```json
"lint": "eslint src"
```

To gate it in CI, add a step to `ci.yml`'s `frontend-unit` job next to the
Prettier one. That job already feeds the `Dev checks passed` aggregator, so
no branch-protection change is needed:

```yaml
      - name: Lint (ESLint)
        run: npm --prefix frontend run lint
```

### Status when this was last checked

Run against all 98 `.ts`/`.tsx` files under `frontend/src/`: **clean, exit
0**. Both rules were confirmed to actually fire by linting a file with a
conditional `useEffect` and a missing dependency, so the clean result is
real coverage rather than a silently mis-parsed config. Versions used:
`eslint@10.9.1`, `eslint-plugin-react-hooks@7.1.1`,
`@babel/eslint-parser@8.0.1`.

Adopting this needs no code cleanup - only the dependency, the config, the
script, and optionally the CI step.

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
