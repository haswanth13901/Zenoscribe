# Zenoscribe

> Every voice, clearly attributed.

Real-time speech-to-text with speaker diarization, a multi-user web UI, and an
admin console. Audio is captured in the browser, streamed to
[Soniox](https://soniox.com) for transcription and speaker separation, and
rendered live as labeled turns (`user-1`, `user-2`, ...). Sessions are saved
per user; an admin can see and manage everything.

## Features

- **Live transcription** with speaker labels, streamed over WebSocket.
- **Speaker diarization** by Soniox, with post-processing (majority vote +
  streak-based takeover) to clean up attribution at turn boundaries.
- **Recording per session** — each session (live transcribe, live translate,
  or a batch upload) saves a `.wav`/`.mp3`, a `.txt` transcript, and a
  metadata row tagged with its `source` (`transcribe` / `translate` /
  `upload`), shown as a pill in the recordings tables.
- **Accounts** — JWT login, per-user recording isolation.
- **Admin console** — register users, reset passwords, activate/deactivate,
  delete (with cascade), view all recordings, filter by user, date, and
  source.
- **Presence** — `last_seen` per user, shown as online/offline in the admin
  table.
- **Date and source filtering** in both the user history drawer and the
  admin console.

## Requirements

- Python 3.10+
- A Soniox API key (https://soniox.com)
- A modern browser (Chrome/Edge/Firefox) for mic capture

## Quickstart (Development)

These instructions get a developer environment up and running from a fresh
clone. For production deployments see the "Production" section below.

Prerequisites

- Python 3.10 or later
- Git
- A modern browser (Chrome/Edge/Firefox)
- Postgres (local install, or via `docker compose up db`)

1) Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

2) Create an environment file

Copy the example file and populate values. Do not commit real secrets to git.

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```
# Soniox API key (required for transcription)
SONIOX_API_KEY=

# JWT signing secret. Required in production; a generated secret is allowed
# in development/testing but should not be used in deployed environments.
JWT_SECRET=

# Initial admin account (set a strong password in production)
ADMIN_USERNAME=admin
ADMIN_PASSWORD=

# Environment mode: development | testing | production
ENV=development

# Optional test hooks (enable only in CI/dev)
ALLOW_TEST_HOOKS=false
TEST_HOOK_SECRET=
RESTRICT_TEST_HOOK_TO_LOCALHOST=true
```

2a) Generate secrets

`JWT_SECRET` and `TEST_HOOK_SECRET` are independent random strings — generate a
separate value for each; do not reuse one for both. `JWT_SECRET` signs login
tokens and is security-critical (rotating it invalidates all existing logins).
`TEST_HOOK_SECRET` is only a shared password on the test-hook endpoint and is
only used when `ALLOW_TEST_HOOKS=true`.

Generate a value with any of these:

```bash
# Python (matches what the app uses internally)
python -c "import secrets; print(secrets.token_urlsafe(48))"

# or OpenSSL (macOS/Linux)
openssl rand -base64 48
```

On Windows PowerShell, the Python one-liner above works as-is.

Paste the first value into `JWT_SECRET`:

```
JWT_SECRET=<generated value>
```

`TEST_HOOK_SECRET` is only needed if you enable the test hooks in dev. If so,
generate a second value and set:

```
ALLOW_TEST_HOOKS=true
TEST_HOOK_SECRET=<second generated value>
RESTRICT_TEST_HOOK_TO_LOCALHOST=true
```

Leave `ALLOW_TEST_HOOKS=false` (and `TEST_HOOK_SECRET` blank) for normal
development and in any deployed environment. When enabled, calls to
`/internal/test-hook/transcribe_mode` must include a matching
`X-TEST-HOOK-SECRET` header and an admin JWT, and are accepted only from
localhost unless `RESTRICT_TEST_HOOK_TO_LOCALHOST=false`.

2b) Start Postgres

```bash
docker compose up -d db
```

Or point `DATABASE_URL` in `.env` at a Postgres instance you already have
running. The app applies Alembic migrations automatically on startup (see
"Data & storage" below), so no separate migration step is needed for a fresh
database.

3) Start the app (development)

```bash
# from the repository root
uvicorn voice_transcriber.server:app --reload --port 8000
```

Open http://localhost:8000 and sign in. The first-run admin user will be
created automatically if no admin exists; in development a generated password may
be used (the app will warn but will not print generated secrets in logs).

Production

For production, enforce the following before starting the app:

- Set `ENV=production`.
- Set a strong `JWT_SECRET` (store it in your secret manager, not in git).
  Keep it stable across deploys — do not rotate it on a schedule, or every
  deploy will log all users out. (`DEV_ROTATE_JWT_ON_RESTART` is a dev-only
  convenience and is ignored when `ENV=production`.)
- Set `ADMIN_PASSWORD` to a secure password meeting the minimum length.
- Optionally tune `TOKEN_HOURS` (default 8) for how long a login lasts before
  it expires and the user must sign in again.

If required secrets are missing or weak in production the app will refuse to
start to avoid insecure defaults.

Start (example):

```bash
# ensure the environment variables are provided by your system/CI/deployment
# from the repository root
uvicorn voice_transcriber.server:app --host 0.0.0.0 --port 8000 --workers 1
```

CI / E2E tests

- The repository includes a GitHub Actions workflow (`.github/workflows/ci.yml`)
  with three jobs: the fast pytest suite, the Playwright integration suite (all
  `test_e2e_playwright_*.py` files), and the frontend Vitest suite.
- No test-hook env vars need to be set at the job level: the `live_server`
  fixture that actually launches the test server always sets its own
  `ALLOW_TEST_HOOKS`/hook secret on the subprocess's environment directly.

Troubleshooting

- If the app fails on startup with a missing-secret error, verify `ENV` and the
  related env vars (`JWT_SECRET`, `ADMIN_PASSWORD`) are set for production.
- Mic capture requires a secure context (HTTPS) except for `localhost` where
  browsers allow getUserMedia over HTTP for development.

Security notes

- Do not enable debug logging that prints transcript or token content in
  production (`DEBUG_TOKENS` is disabled by default).
- Do not commit `.env` or any secret material to the repository.

For full developer reference see the Project structure section below.


## Developer quickchecks

These commands help verify a fresh developer environment is correctly configured.

1) Bootstrap (create venv, install deps, Playwright browsers):

```bash
# POSIX
bash scripts/bootstrap.sh

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
```

2) Activate the virtualenv and run a quick smoke check:

```bash
# POSIX
source .venv/bin/activate
python -m uvicorn voice_transcriber.server:app --port 8000
# then open http://localhost:8000
```

3) Run the test suite (Playwright must be installed for the E2E test):

```bash
# Fast suite: isolated unit/API tests (no live server, no network, <10s)
pytest -q

# Full black-box E2E test: launches a real server subprocess + headless
# Chromium via Playwright
pytest -q -m integration

# Real Soniox network tests. The network-timeout test always runs; the
# credentialed test spends real API quota and stays skipped unless you
# explicitly opt in (SONIOX_API_KEY alone is not enough, since .env can
# supply it without you intending to spend it in a test run):
RUN_REAL_SONIOX_TESTS=true pytest -q -m real_network
```

4) Run with Docker (local parity with CI):

```bash
# Build and run
docker-compose up --build
# Visit http://localhost:8000
```

These quickchecks are intended for development and CI; do not enable debug
logging or test hooks in production. See the Production section above for
secure deployment requirements.

### VS Code performance (optional)

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

## Frontend (React + Redux Toolkit)

All post-login pages — `/home`, `/app` (the recorder), `/admin`,
`/translate`, `/recordings` (a user's own recordings, formerly a slide-out
drawer over `/app`) and `/upload` (the batch transcribe form, formerly a
`?upload=1` panel over `/app` or `/admin`) — are migrated off vanilla JS,
completing the staged plan in `Update_Roadmap.txt` (`/home` → recorder →
admin → translate). All six are client-side routes of one SPA in
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
no second directory. `server.py` (`config.FRONTEND_DIST_DIR`) serves
straight out of `frontend/dist/`: `/`, `/login`, and the `/static/*` mount
all read from it directly, and so do `/home`, `/app`, `/admin`,
`/translate`, `/recordings` and `/upload` (all serving
`frontend/dist/index.html`, the SPA shell).
There is no `voice_transcriber/static/` any more.

The old vanilla `home.html`/`index.html`/`admin.html`/`translate.html` and
the shared scripts they used
(`header.js`/`sidebar.js`/`theme-toggle.js`/`upload.js`/`recorder-turns.js`/
`translate-views.js`) were kept as a rollback path through the migration
and have since been deleted, now that the SPA is confirmed stable — restore
them from git history (`git log -- voice_transcriber/static/`) if ever
needed.

Dev — there is no separate frontend dev server; FastAPI on `:8000` is the
only thing you run, and it serves the frontend straight out of
`frontend/dist/`. Build once, then start the backend:

```bash
npm --prefix frontend install   # first time only
npm --prefix frontend run build
uvicorn voice_transcriber.server:app --reload --port 8000
```

Open http://localhost:8000/home (or `/app`, `/admin`, `/translate`,
`/recordings`, `/upload`, or `/login`). This writes everything the backend
needs straight to
`frontend/dist/` — the SPA shell, its hashed assets, and (via Vite's
public-dir copy) `login.html`, `theme.css`, `theme-preboot.js` and
`pcm-worklet.js`. Nothing else to copy, in Docker or out of it — the
`Dockerfile`'s final stage just copies `frontend/dist/` from the build stage
into the image at the same path.

After any frontend change, rerun `npm --prefix frontend run build` and
refresh the browser — there's no hot-reload, since Vite's dev server isn't
used at all here.

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

### Frontend source layout (Feature-Sliced Design)

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

## Project structure

```
server.py         Thin entrypoint: app, page routes, mounts the two routers
config.py         Paths + transcription tuning constants
transcribe.py     Realtime engine: Soniox WebSocket bridge, turn detection
routes_api.py     Auth, user administration, recording access
auth.py           JWT, bcrypt, role guards
db.py             Postgres storage (users, recordings, presence)
soniox_client.py  Soniox REST + WebSocket config, speaker labeling
frontend/          Single source dir for every frontend file (Vite + React +
                   TypeScript + Redux Toolkit). Builds to frontend/dist/
                   (gitignored), served directly by server.py - see
                   "Frontend" above.
  public/            Files served as-is, not processed by Vite: login.html
                     (still vanilla, pre-auth), theme.css/theme-preboot.js
                     (shared dark-mode styling/boot), pcm-worklet.js (mic
                     capture AudioWorklet, loaded by raw URL)
  src/               React + Redux Toolkit source for all six post-login
                     pages, in Feature-Sliced Design layers - see "Frontend
                     source layout" above
```

The two routers (`routes_api`, `transcribe`) never import each other — both
depend only on `auth`, `db`, and `config`. The transcription engine can be
retuned without touching login behaviour.

## How diarization works

Two independent layers:

1. **Soniox** does the actual speaker separation from the audio and attaches a
   speaker id to each token. This is the hard part and happens entirely on
   their side.
2. **This app** only cleans up the resulting labels — majority vote per turn,
   streak-based takeover, and carry-back — so a wrong label on the first word
   of a turn gets corrected by the rest. It cannot separate speakers Soniox
   failed to separate.

If speakers are being merged, set `DEBUG_SPEAKERS = True` in `config.py` and
watch the raw ids. If they don't alternate, the fix is upstream: pass
`num_speakers`, improve mic placement, or use separate channels. The single
biggest accuracy lever is the input audio, not the post-processing.

## Tuning turn detection

All in `config.py`:

| Constant | Meaning |
|---|---|
| `IDLE_FLUSH_SEC` | Close a turn after this much silence (default 1.6s) |
| `MAX_TURN_CHARS` | Hard cap so a turn stays readable (default 400) |
| `SENTENCE_PAUSE_SEC` | Pause required before punctuation ends a turn |
| `VOTE_MARGIN` | Consecutive tokens a new speaker needs to take over |
| `LANGUAGE_HINTS` | e.g. `["en"]`; add more for code-switching |
| `DEBUG_SONIOX` / `DEBUG_SPEAKERS` | Verbose logging toggles |

## Data & storage

- **Postgres** — users, recording metadata, presence. Connection configured via
  `DATABASE_URL` (see `.env.example`); for local dev this points at the `db`
  service in `docker-compose.yml`. Schema is managed with
  [Alembic](https://alembic.sqlalchemy.org/) migrations in `alembic/versions/`;
  `db.init()` runs `alembic upgrade head` automatically at startup, so a fresh
  database is migrated on first run same as before. To manage migrations
  directly: `alembic upgrade head`, `alembic revision -m "..."`.
- **`recordings/`** — saved `.wav`/`.mp3` and `.txt` files. Deliberately *not*
  served as static files; all access goes through authenticated,
  ownership-checked API routes.
- **`recordings.source`** — one of `transcribe` / `translate` / `upload`
  (`db.RECORDING_SOURCES`), recording which flow produced the row: a live
  transcription session, a live translate session, or a batch upload via
  `/api/transcribe` or `/api/transcribe/translate`. `GET /api/recordings`
  accepts an optional `source` filter alongside `user_id`/`date_from`/`date_to`.

`recordings/` is not committed to git (see `.gitignore`); neither is `.env`
(which holds `DATABASE_URL` and other secrets).

If `recordings/` and the `recordings` table ever drift out of sync (e.g. a
partial failure mid-save), `scripts/reconcile_recordings.py` reports files on
disk with no matching DB row and DB rows pointing at missing files. It's a
dry-run report by default; pass `--delete` to also remove orphaned files (it
never touches the database):

```bash
python scripts/reconcile_recordings.py            # report only
python scripts/reconcile_recordings.py --delete   # also delete orphan files
```

## Security notes

- Recordings are never publicly served; every download checks ownership
  (admins can access any; users only their own).
- Deactivating a user immediately invalidates their existing token (re-checked
  against the DB on each request, not just at expiry).
- Guards prevent an admin from deactivating/deleting themselves or removing the
  last remaining admin.
- Live transcription authenticates on the first WebSocket frame after the
  socket opens, so the JWT is not exposed in the URL/query string where it
  could appear in server or proxy logs.
  over plain HTTP. **Put this behind HTTPS before deploying beyond localhost.**

### Sessions & tokens

- Login issues a JWT stored in the browser's `sessionStorage`, so closing the
  tab clears the session.
- Every protected page (`/app`, `/admin`, `/translate`, `/home`) checks
  `sessionStorage` for a token and user on load and redirects to `/login`
  immediately if either is missing — the page itself is not gated
  server-side, but every API call behind it is. A token that's present but
  stale/expired/invalid is only caught on the first authenticated request:
  the shared `api()`/fetch wrapper on each page (an RTK Query base query on
  `/home`) clears storage and redirects to `/login` on a `401`.
- Tokens expire after `TOKEN_HOURS` (default 8). Expiry is baked into each
  token, so a continuously running server does not keep anyone logged in past
  their window — the next request after expiry returns 401 and the page
  redirects to login. There is no automatic refresh; the user logs in again to
  get a fresh token.
- `JWT_SECRET` is a stable signing key, not something to rotate on a schedule.
  Set it once. Changing it invalidates every existing token at once — useful as
  a "log everyone out now" switch after a suspected leak, but not for routine
  operation.
- **Forcing re-login on a dev restart:** set `DEV_ROTATE_JWT_ON_RESTART=true` in
  a development `.env`. The secret is then regenerated on every startup, so
  restarting the dev server invalidates all tokens and sends every open page
  back to login. This flag is ignored in production, where the fixed
  `JWT_SECRET` is always used so deploys/restarts don't log real users out.

## Batch (non-live) transcription

`soniox_client.transcribe_file(path)` uploads a `.wav`/`.mp3` and returns merged
speaker turns using the async API, which has full-file context and is more
accurate than the live path. Exposed at `POST /api/transcribe` (authenticated),
and at `POST /api/transcribe/translate` for the same upload plus server-side
one-way translation.

A non-empty result from either endpoint is persisted the same way a live
session is — the uploaded audio is moved into `recordings/` (keeping its
original extension), a `.txt` transcript is written, and a `recordings` row is
added with `source="upload"` — so batch uploads show up in My/All Recordings
alongside live sessions. This is best-effort: a storage/DB failure here is
logged but does not turn an otherwise-successful transcription into an error
response for the caller.
