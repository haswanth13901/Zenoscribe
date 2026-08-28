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
  table. Refreshed at most once per `LAST_SEEN_DEBOUNCE_SEC` (default 60s)
  rather than on every request.
- **Date and source filtering** in both the user history drawer and the
  admin console.

## Branching

`dev` is the default branch and where day-to-day work lands; `main` is
production - every commit there has passed the full release gate and is
deployable. Both branches carry the identical file set; environment is
selected by which compose/env file you use, never by which branch you're
on. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full model, the release
flow, and the CI tiers.

## Quickstart (Development)

From a fresh clone to a running dev environment. For production, see
[DEPLOYMENT.md](DEPLOYMENT.md).

**Prerequisites** - Python 3.10+, Git, a [Soniox](https://soniox.com) API
key, a modern browser (Chrome/Edge/Firefox, for mic capture), plus Postgres
and Redis (both available via `docker compose up -d db redis` if you don't
have them locally).

**1) Install dependencies**

```bash
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

`requirements-dev.txt` layers dev/test tooling (pytest, Playwright, flake8,
`record.py`'s CLI-only deps) on top of `requirements.txt` via
`-r requirements.txt`. `requirements.txt` alone is the production set - it's
what the Dockerfile installs; keep dev/test/lint packages out of it.

**2) Create an environment file**

```bash
cp .env.example .env
```

`.env.example` documents every variable. At minimum set `SONIOX_API_KEY`,
`JWT_SECRET` and `ADMIN_PASSWORD`; leave `ENV=development`. Never commit real
secrets.

`JWT_SECRET` and `TEST_HOOK_SECRET` are independent random strings - generate
a separate value for each, don't reuse one for both. `JWT_SECRET` signs login
tokens and is security-critical (rotating it logs everyone out);
`TEST_HOOK_SECRET` is only a shared password on the test-hook endpoint and
only matters when `ALLOW_TEST_HOOKS=true`, which stays `false` outside CI/dev.

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

**3) Start Postgres and Redis, then migrate**

```bash
docker compose up -d db redis
python -c "from voice_transcriber import db; db.init()"
```

Migrations do **not** apply automatically at app startup - see
[docs/architecture.md](docs/architecture.md) for why. `docker compose up` runs
the migration for you via the one-shot `migrate` service; the explicit call
above is only needed when running `uvicorn` outside Compose.

**4) Start the app**

Three ways, depending on whether you're editing the frontend:

```bash
# a) Backend only - frontend already built, or you're not touching it
uvicorn voice_transcriber.server:app --reload --port 8000

# b) Backend + Vite dev server with hot-reload, two terminals
uvicorn voice_transcriber.server:app --port 3000   # terminal 1
npm --prefix frontend run dev                      # terminal 2

# c) Fully containerized, same split, no host npm/uvicorn at all
docker compose up -d
```

All three end up at http://localhost:8000. In (b) and (c) Vite serves the
React app there and proxies `/api`, `/healthz`, `/ws`, `/ws/translate` and the
vanilla `/` and `/login` pages through to the backend on `:3000`, so the
browser sees one effective origin. See [docs/frontend.md](docs/frontend.md)
for how that split works and when to prefer each option.

On first run the admin user is created automatically if no admin exists. In
development a generated password may be used - the app warns, and never prints
generated secrets to logs.

## Production

Don't deploy from this section - the runbook is
[DEPLOYMENT.md](DEPLOYMENT.md), covering TLS bootstrap, first-boot admin
seeding, scaling `web` beyond one replica, backups, rollback, and a pre-deploy
gate checklist.

```bash
cp .env.production.example .env.production   # fill in real values
./scripts/init-letsencrypt.sh                # one-time TLS bootstrap
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

The one thing worth repeating here, because it fails silently: **`ENV` must
reach the app as a real process environment variable.** `config.py` loads
`.env.<ENV>` only once it knows which `ENV` it's in, so putting
`ENV=production` inside `.env.production` does nothing on the bare `uvicorn`
path. Under `docker-compose.prod.yml`, `web`'s `env_file:` line does inject
it. Get this wrong and the app starts in `development` mode - generated JWT
secret, auto-created admin, every production fail-fast guard bypassed - with
no error at startup, because development is a valid mode. The full breakdown
per run path - bare `uvicorn`, Compose, plain `docker run` - is in
[DEPLOYMENT.md](DEPLOYMENT.md) under "How `ENV` and `.env.production` actually
reach the process", along with the single-combined-container path and the gate
checklist that proves it didn't happen.

`docker-compose.yml` is local development only; use `docker-compose.prod.yml`
for production.

Health check: `GET /healthz` reports liveness plus a Postgres readiness check,
unauthenticated by design. It's already wired into `docker-compose.prod.yml`'s
`web` healthcheck - point external uptime monitoring at it too.

## Developer quickchecks

```bash
# Bootstrap: venv, deps, Playwright browsers; starts db/redis if Docker is
# available and verifies both are reachable (see scripts/check_deps.py)
bash scripts/bootstrap.sh                                       # POSIX
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1  # Windows

# Lint - matches CI's backend-lint job exactly
flake8 voice_transcriber scripts --max-line-length=120

# Fast suite: isolated unit/API tests, no live server, no network (~90s).
# Needs no real Redis - conftest.py's isolated_redis fixture stands in.
pytest -q

# Integration suite: launches a real server subprocess + headless Chromium
# via Playwright. This one does need a real Redis at REDIS_URL.
pytest -q -m integration

# Real Soniox network tests. The timeout test always runs; the credentialed
# one spends real API quota and stays skipped unless you opt in explicitly
# (SONIOX_API_KEY alone is not enough - .env can supply it unintentionally).
RUN_REAL_SONIOX_TESTS=true pytest -q -m real_network

# Frontend
npm --prefix frontend run test
npm --prefix frontend run format:check
```

Both images run as a non-root user (the Dockerfile's `USER app`). On a Linux
dev host, if the bind-mounted `voice_transcriber/` ends up owned by a UID the
container's `app` user can't write to, recording saves fail with a permission
error - `docker compose run --user root web chown -R app:app
/app/voice_transcriber` once is the fix.

Don't enable debug logging or test hooks in production.

## Architecture

```
server.py         Thin entrypoint: app, page routes, mounts the two routers
config.py         Paths + transcription tuning constants
transcribe.py     Realtime engine: Soniox WebSocket bridge, turn detection
routes_api.py     Thin aggregator over routers/
routers/          One module per API domain: auth, admin, recordings,
                  uploads, test_hooks
auth.py           JWT, bcrypt, role guards
db.py             Postgres storage (users, recordings, presence)
soniox_client.py  Soniox REST + WebSocket config, speaker labeling
frontend/          Single source dir for every frontend file (Vite + React +
                   TypeScript + Redux Toolkit). Builds to frontend/dist/
                   (gitignored), served directly by server.py in dev -
                   see docs/frontend.md
  public/            Files served as-is, not processed by Vite: login.html
                     (still vanilla, pre-auth), theme.css/theme-preboot.js
                     (shared dark-mode styling/boot), pcm-worklet.js (mic
                     capture AudioWorklet, loaded by raw URL)
  src/               React + Redux Toolkit source for all six post-login
                     pages, in Feature-Sliced Design layers - see
                     docs/frontend.md
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
- Mic capture needs a secure context: browsers allow `getUserMedia` over plain
  HTTP only on `localhost`. **Put this behind HTTPS before deploying beyond
  localhost.**

Session lifetime, token expiry, `JWT_SECRET` rotation and `SERVER_BOOT_ID`
are covered in [docs/architecture.md](docs/architecture.md).

## Documentation

| Document | What's in it |
|---|---|
| [CONTRIBUTING.md](CONTRIBUTING.md) | Branch model, release and hotfix flows, the four CI tiers, commit conventions |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Production runbook: env vars, TLS, scaling, backups, rollback, pre-deploy gate |
| [docs/frontend.md](docs/frontend.md) | `frontend/` architecture, dev workflows, Feature-Sliced Design layout |
| [docs/architecture.md](docs/architecture.md) | Data and storage, sessions and tokens, turn-detection tuning, batch transcription |
| [docs/github-repo-settings.md](docs/github-repo-settings.md) | Branch protection, required checks, CI secrets and variables |
| [docs/audits/](docs/audits/) | Point-in-time audit and design writeups: deployment readiness, scalability, E2E review |
| [CHANGELOG.md](CHANGELOG.md) | Release notes |
