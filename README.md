# Zenoscribe

[![CI](https://github.com/haswanth13901/Zenoscribe/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/haswanth13901/Zenoscribe/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)

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

## Branching

`dev` is the default branch and where day-to-day work lands; `main` is
production - every commit there has passed the full release gate and is
deployable. Both branches carry the identical file set; environment is
selected by which compose/env file you use, never by which branch you're
on. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full model, the release
flow, and the CI tiers.

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
- Redis (local install, or via `docker compose up redis`) — required, not
  optional: rate limiting has no in-memory fallback any more (see
  "Data & storage" below)

1) Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

`requirements-dev.txt` layers local dev/test tooling (pytest, Playwright,
flake8/black, plus `record.py`'s CLI-only deps) on top of
`requirements.txt` via `-r requirements.txt`. `requirements.txt` alone is
the production-only set — it's what the Dockerfile's production image
installs; keep dev/test/lint packages out of it.

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

# Redis connection string - required (rate limiting has no in-memory
# fallback). Defaults to the `redis` service in docker-compose.yml.
REDIS_URL=redis://localhost:6379/0

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

2b) Start Postgres and Redis, then run migrations

```bash
docker compose up -d db redis
python -c "from voice_transcriber import db; db.init()"
```

Or point `DATABASE_URL`/`REDIS_URL` in `.env` at instances you already have
running. Migrations no longer apply automatically on app startup (see
"Data & storage" below) — this is now an explicit one-time step for a fresh
database (`docker compose up` runs it for you automatically via the
`migrate` service; running it directly like above is only needed if you're
running `uvicorn` outside Compose).

3) Start the app (development)

Two options, depending on whether you're touching the frontend:

**Backend only** (frontend already built, or you're not changing it):

```bash
# from the repository root
uvicorn voice_transcriber.server:app --reload --port 8000
```

Open http://localhost:8000 and sign in.

**Backend + frontend, with hot-reload** (recommended when iterating on
`frontend/`) — two terminals, backend on `:3000` and a real Vite dev server
on `:8000`:

```bash
# terminal 1 - backend, no --reload needed for frontend-only edits
uvicorn voice_transcriber.server:app --port 3000

# terminal 2
npm --prefix frontend run dev
```

Open http://localhost:8000 — Vite serves the React app there with HMR and
proxies `/api`, `/healthz`, `/ws`, `/ws/translate`, and the two vanilla
pages (`/` and `/login`) through to the backend on `:3000`, so the browser
sees one effective origin. See "Frontend" below for how this split works
and when you'd use it over the single-port option above.

**Fully containerized, with hot-reload** (no host-side `npm`/`uvicorn` at
all - same split as above, just each half in its own container instead of
its own terminal):

```bash
docker compose up -d
```

Open http://localhost:8000, same as the two-terminal option. `db`, `redis`,
`migrate`, `web`, and `frontend` all come up together - see "Frontend"
below for what `frontend`'s container does and why it needs `WATCH_POLL`.

Either way, the first-run admin user will be created automatically if no
admin exists; in development a generated password may be used (the app
will warn but will not print generated secrets in logs).

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

You can provide these either as real process env vars (system/CI/platform
secrets UI), or via a `.env.production` file:

```bash
cp .env.production.example .env.production
# edit .env.production and fill in real values
```

`voice_transcriber/config.py` loads `.env.<ENV>` (e.g. `.env.production`) if
it exists, falling back to plain `.env` otherwise. `ENV` itself still has to
be set as a real process env var — the app needs it before it knows which
file to load. `.env.production` is git- and docker-ignored, same as `.env`;
never commit it.

**What "real process env var" means depends on how you run the app** — this
trips people up specifically under Compose, so read this if that's your
path:

- **Bare `uvicorn`/`python`, no container:** `ENV=production` must be set on
  the shell/process directly (`ENV=production uvicorn ...`). Putting it
  inside `.env.production` does nothing here — nothing has told the process
  which file to load yet, so nothing has loaded it.
- **`docker-compose.prod.yml` (this repo's production Compose file):**
  `web`'s `env_file: .env.production` line *does* inject every line in that
  file — `ENV=production` included — as real container process env vars,
  before the app starts. You do not need to also pass `-e ENV=production`
  separately; `env_file:` already covers it. This is *not* the same
  mechanism as the top-level `--env-file .env.production` flag used
  elsewhere on the `docker compose` command line (that one only affects
  `${VAR}` substitution inside the YAML file itself, e.g. `${POSTGRES_USER}`
  — see `docker-compose.prod.yml`'s header comment). Both point at the same
  file here, but they do different jobs.
- **Plain `docker run`:** neither `env_file:` nor Compose's `--env-file`
  apply. Use `--env-file .env.production -e ENV=production` as shown below
  (or bake `ENV=production` into the image, which this repo does not do).

Getting this wrong is exactly what silently starts the app in
`development` mode instead of `production` — the generated JWT secret, the
auto-created admin, and every production fail-fast guard bypassed, with no
error at startup because development mode is a valid mode. See
DEPLOYMENT.md's gate checklist for how to prove this didn't happen
(blank out `JWT_SECRET` and confirm the app refuses to start).

Start (example):

```bash
# ENV=production must be a real process env var; the rest can come from
# .env.production (see above) or your system/CI/deployment secrets
ENV=production uvicorn voice_transcriber.server:app --host 0.0.0.0 --port 8000 --workers 1
```

Docker Compose (recommended — this is what `docker-compose.prod.yml` and
`frontend/nginx.conf` in this repo are set up for; single VM behind nginx
for TLS, certificate managed by a certbot sidecar). Seven services: `db`
(stock `postgres:16-alpine`), `redis` (stock `redis:7-alpine` — shared
rate-limit counters), `minio` (stock `minio/minio` — shared recording
storage), `migrate` (one-shot: applies Alembic migrations, then exits),
`web` (backend only — API/WS routes, nothing else; stateless, safe to run
multiple replicas of — see "Scaling" below), `nginx` (TLS termination,
routing to `web`, and the SPA/login page, all in one container — see
`frontend/nginx.conf`), and `certbot` (obtains/renews the Let's Encrypt
certificate `nginx` serves):

```bash
cp .env.production.example .env.production   # fill in real values, incl. DOMAIN/CERTBOT_EMAIL
# edit frontend/nginx.conf: replace your-domain.example.com with your real domain
./scripts/init-letsencrypt.sh                 # one-time TLS bootstrap - see DEPLOYMENT.md
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

The `--env-file .env.production` flag on the `docker compose` command is
required and is a different mechanism from `web`'s `env_file:` line inside
`docker-compose.prod.yml` — see the comment at the top of that file, and
DEPLOYMENT.md, for why both are needed. See DEPLOYMENT.md for the full
runbook: the TLS bootstrap step, first-boot admin seeding, backups, restart
behaviour, rollback.

Docker (single combined container, no Compose — example). A bare `docker
build .` now produces the lean backend-only image (the Dockerfile's default
target), so this path needs `--target backend-with-frontend` explicitly —
the same combined backend+frontend image `docker-compose.yml` (dev) uses,
frontend/dist/ baked in and all. `STORAGE_BACKEND` must be `minio` in
production (the app refuses to start with `local`, which isn't shared
across anything) — you need real Postgres/Redis/MinIO endpoints reachable
from this container, set via `DATABASE_URL`/`REDIS_URL`/`MINIO_*` in
`.env.production`, since there's no Compose network to resolve service
names on in this path:

```bash
docker build --target backend-with-frontend -t zenoscribe .
docker run -p 8000:8000 -e ENV=production --env-file .env.production zenoscribe
```

No recordings volume is needed here any more — once `STORAGE_BACKEND=minio`,
the only thing the container ever writes locally is an ephemeral
live-session scratch file, gone the moment that session ends (see
`config.live_scratch_dir()`); the durable data lives in MinIO/Postgres, both
external to this container. You are on your own for TLS termination in this
path — the Compose path above gets it from nginx (certificate managed by the
`certbot` sidecar).

Either way, this assumes a single VM for `db`/`redis`/`minio` themselves -
none of those three have been made highly available, only `web` is
horizontally scalable. See DEPLOYMENT.md's "If you scale beyond one VM"
section for what that does and doesn't cover.

Both the backend and the combined single-container image run as a non-root
user (`USER app` in the Dockerfile) with `--workers 1` pinned explicitly —
see the Dockerfile's comments for why raising worker count per container is
unsafe without further changes; scale by running more containers instead
(see "Scaling" below).

**Scaling `web` to multiple replicas** (plain Docker Compose, no
Kubernetes/Swarm needed):

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml \
  up -d --scale web=3
```

This works because `web` is stateless: recordings go through the shared
`minio` service, rate limits through the shared `redis` service, and every
replica validates the same required `SERVER_BOOT_ID`.
`frontend/nginx.conf`'s `resolver`/`$backend` directives are what make nginx
actually spread requests across the replicas Docker's DNS returns, instead
of pinning to whichever one it resolved first. See DEPLOYMENT.md's
"Scaling" section for `DB_POOL_MAX_SIZE` sizing guidance as you add
replicas, and `HORIZONTAL_SCALABILITY_READINESS.md` for this work's
verification status — **run its multi-replica validation on your own VM
before relying on this in production**; `docker-compose.prod.yml`
specifically has not been run in this repo's own tool environment (Docker
itself is available and `docker-compose.yml`'s dev stack has been run on it
end to end, but not this file).

Note: `docker-compose.yml` in this repo is for local development only (it
bind-mounts source for live-edit, defaults to `.env`, and runs `web` and
`frontend` as separate containers, with `web` also baking in a
`backend-with-frontend` build for the vanilla `/`/`/login` pages — see
"Frontend" above) — don't use it for production; use
`docker-compose.prod.yml` instead.

Health check: `GET /healthz` reports liveness plus a Postgres readiness
check (`{"status": "ok", "database": "ok"}`, or a 503 with `"degraded"` if
the database is unreachable). It's unauthenticated by design — deliberately
returns nothing beyond ok/degraded, no version or config — and is wired
into `docker-compose.prod.yml`'s `web` healthcheck already; point external
uptime monitoring at it too (over HTTPS, once TLS is bootstrapped — see
DEPLOYMENT.md). `nginx` has its own separate, simpler healthcheck (a fixed
plain-HTTP `/healthz-nginx` response) purely for Compose's own
`restart:`/`depends_on` bookkeeping — not a substitute for watching
`/healthz`.

CI / E2E tests

- The repository includes a GitHub Actions workflow (`.github/workflows/ci.yml`)
  with six jobs: a `flake8` lint gate over `voice_transcriber`/`scripts`, the
  fast pytest suite, the Playwright integration suite (all
  `test_e2e_playwright_*.py` files), the frontend Vitest suite, a production
  Docker image build (a sanity check for non-root and no leaked `.env` file,
  plus a Trivy scan of the built image that fails on `CRITICAL`/`HIGH`
  vulnerabilities), and a dependency audit (`pip-audit` on `requirements.txt`,
  `npm audit` on the frontend). `.github/dependabot.yml` separately opens
  weekly version-bump PRs for pip, npm, the Dockerfile base image, and the
  workflow's own GitHub Actions.
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

1) Bootstrap (create venv, install deps, Playwright browsers; also starts
   `db`/`redis` via Docker if available and verifies both are reachable —
   see `scripts/check_deps.py`):

```bash
# POSIX
bash scripts/bootstrap.sh

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
```

2) Activate the virtualenv and run a quick smoke check. Needs a real
   Postgres and Redis reachable (`docker compose up -d db redis`, or your
   own instances via `DATABASE_URL`/`REDIS_URL`), and the DB migrated once
   (`python -c "from voice_transcriber import db; db.init()"` — see "Data &
   storage" below for why this is a separate step now):

```bash
# POSIX
source .venv/bin/activate
python -m uvicorn voice_transcriber.server:app --port 8000
# then open http://localhost:8000
```

3) Run the test suite (Playwright must be installed for the E2E test). The
   fast suite (`pytest -q`) needs no real Redis - it uses an in-process
   fakeredis stand-in (see conftest.py's `isolated_redis` fixture) - but the
   integration suite below launches a real server subprocess and does need
   a real Redis reachable at `REDIS_URL`/its default:

```bash
# Lint: matches CI's backend-lint job exactly
flake8 voice_transcriber scripts --max-line-length=120

# Fast suite: isolated unit/API tests (no live server, no network, ~90s)
pytest -q

# Full black-box E2E test: launches a real server subprocess + headless
# Chromium via Playwright (needs a real Redis - see above)
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
# Visit http://localhost:3000
```

The image runs as a non-root user (Dockerfile's `USER app`). On Docker
Desktop (Windows/macOS) this bind-mounts fine. On a Linux dev host, if the
bind-mounted `voice_transcriber/` ends up owned by a UID the container's
`app` user can't write to, recording saves will fail with a permission
error — `docker compose run --user root web chown -R app:app
/app/voice_transcriber` once is the fix, or match your host UID to the
container's via a build arg if this comes up often.

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
simply don't register on `web`. See DEPLOYMENT.md for the full production
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
the "Production" section above. `web` (dev) still also bakes `frontend/dist/`
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
  [Alembic](https://alembic.sqlalchemy.org/) migrations in `alembic/versions/`.
  **Migrations no longer apply automatically at app startup** (this changed
  once running more than one `web` replica became supported - concurrent,
  uncoordinated `alembic upgrade head` calls from several replicas starting
  at once could race). `db.init()` still runs them (idempotent, safe to call
  against an already-current database), but it's now an explicit step -
  `docker compose up` runs it for you via the one-shot `migrate` service; the
  app's own startup only *verifies* the schema matches what the code expects
  (`db.verify_schema_current()`) and refuses to serve otherwise. To manage
  migrations directly: `alembic upgrade head`, `alembic revision -m "..."`.
- **Redis** — rate-limit counters only (`rate_limit.py`), never durable data.
  Connection configured via `REDIS_URL` (see `.env.example`); for local dev
  this points at the `redis` service in `docker-compose.yml`. Losing Redis
  (restart, outage) never loses data - rate limiting fails closed (503) until
  it's back, rather than silently allowing unlimited requests through.
- **Recording storage** (`voice_transcriber/storage/`) — audio + transcript
  objects, addressed by an opaque key (`users/{user_id}/recordings/{id}.wav`
  etc.), never a raw filesystem path. Two backends:
  - `STORAGE_BACKEND=local` (dev/test default) — writes under
    `voice_transcriber/recordings/`, matching the key layout above.
  - `STORAGE_BACKEND=minio` (required in production) — a self-hosted
    S3-compatible object store, shared across every `web` replica (unlike a
    local directory, which only one replica could ever see). See
    `docker-compose.yml`'s opt-in `minio` service for local testing against a
    real MinIO instance, and `SCALABILITY_DESIGN.md` §2 for the full design.
  Neither backend is ever served as static files; all access goes through
  authenticated, ownership-checked API routes (`_authorize_recording()` in
  `routes_api.py`), regardless of which backend answers the read.
- **`recordings.source`** — one of `transcribe` / `translate` / `upload`
  (`db.RECORDING_SOURCES`), recording which flow produced the row: a live
  transcription session, a live translate session, or a batch upload via
  `/api/transcribe` or `/api/transcribe/translate`. `GET /api/recordings`
  accepts an optional `source` filter alongside `user_id`/`date_from`/`date_to`.

`voice_transcriber/recordings/` is not committed to git (see `.gitignore`);
neither is `.env` (which holds `DATABASE_URL`/`REDIS_URL` and other secrets).

If stored recordings and the `recordings` table ever drift out of sync (e.g.
a partial failure mid-save, or a MinIO hiccup - the storage-upload steps in
transcribe.py/translate.py/routes_api.py are deliberately best-effort so a
storage blip doesn't turn an otherwise-successful session into an error),
`scripts/reconcile_recordings.py` reports stored objects with no matching DB
row and DB rows pointing at missing objects. Works against either storage
backend. It's a dry-run report by default; pass `--delete` to also remove
orphaned objects (it never touches the database):

```bash
python scripts/reconcile_recordings.py            # report only
python scripts/reconcile_recordings.py --delete   # also delete orphan objects
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
  `JWT_SECRET` is always used — but that alone does *not* mean deploys/restarts
  leave real users logged in. A separate mechanism does log everyone out on
  every restart by default: see `SERVER_BOOT_ID` below.
- **`SERVER_BOOT_ID` — required in production.** Independently of
  `JWT_SECRET`, every issued token is stamped with the boot ID of the server
  process that issued it (`auth.py`), and a token whose `boot` doesn't match
  the *currently running* process is rejected. In development, leaving it
  unset generates a fresh random boot ID per process start — so a plain
  `docker compose restart`, a crash loop, or a host reboot logs out every
  user even though `JWT_SECRET` never changed. In production the app now
  refuses to start without an explicit value: with more than one `web`
  replica, each generating its own random value would mean a token issued by
  one replica gets rejected by another (random 401s depending on which
  replica a load balancer routes a request to) - see
  `SCALABILITY_AUDIT.md` finding F3. Set `SERVER_BOOT_ID` to a fixed value
  in `.env.production` (see `.env.production.example`), the same value read
  by every replica, so restarts (and now, replicas) don't log anyone out.
  There is no way to revoke a single session early either way — see
  DEPLOYMENT.md's limitations section.

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
