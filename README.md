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
- **Recording per session** — each session saves a `.wav`, a `.txt`
  transcript, and a metadata row.
- **Accounts** — JWT login, per-user recording isolation.
- **Admin console** — register users, reset passwords, activate/deactivate,
  delete (with cascade), view all recordings, filter by user and date.
- **Presence** — `last_seen` per user, shown as online/offline in the admin
  table.
- **Date filtering** in both the user history drawer and the admin console.

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

1) Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

2) Create an environment file

Copy the example file and populate values. Do not commit real secrets to git.

```bash
cp Voice-transcriber/.env.example Voice-transcriber/.env
```

Edit `Voice-transcriber/.env` and set at minimum:

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

3) Start the app (development)

```bash
# from repository root
uvicorn Voice-transcriber.server:app --reload --port 8000
```

Open http://localhost:8000 and sign in. The first-run admin user will be
created automatically if no admin exists; in development a generated password may
be used (the app will warn but will not print generated secrets in logs).

Production

For production, enforce the following before starting the app:

- Set `ENV=production`.
- Set a strong `JWT_SECRET` (store it in your secret manager, not in git).
- Set `ADMIN_PASSWORD` to a secure password meeting the minimum length.

If required secrets are missing or weak in production the app will refuse to
start to avoid insecure defaults.

Start (example):

```bash
# ensure the environment variables are provided by your system/CI/deployment
uvicorn Voice-transcriber.server:app --host 0.0.0.0 --port 8000 --workers 1
```

CI / E2E tests

- The repository includes an opinionated GitHub Actions workflow that runs the
  Playwright E2E test (`.github/workflows/playwright-e2e.yml`). The workflow
  expects `TEST_HOOK_SECRET` to be provided via repository secrets and enables
  test hooks during the job.

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
python -m uvicorn Voice-transcriber.server:app --port 8000
# then open http://localhost:8000
```

3) Run unit/E2E tests (Playwright must be installed):

```bash
# Run pytest and the focused E2E test
pytest -q Voice-transcriber/tests/test_e2e_playwright_upload.py
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
## Project structure

```
server.py         Thin entrypoint: app, page routes, mounts the two routers
config.py         Paths + transcription tuning constants
transcribe.py     Realtime engine: Soniox WebSocket bridge, turn detection
routes_api.py     Auth, user administration, recording access
auth.py           JWT, bcrypt, role guards
db.py             SQLite storage (users, recordings, presence)
soniox_client.py  Soniox REST + WebSocket config, speaker labeling
static/
  login.html      Sign-in page
  index.html      Recorder + history drawer
  admin.html      Admin console
  pcm-worklet.js  Browser mic -> 16 kHz PCM
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

- **`app.db`** — SQLite: users, recording metadata, presence. Created on first
  run; schema migrations are applied automatically at startup.
- **`recordings/`** — saved `.wav` and `.txt` files. Deliberately *not* served
  as static files; all access goes through authenticated, ownership-checked API
  routes.

Neither is committed to git (see `.gitignore`).

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
- Tokens live in `sessionStorage`, so closing the tab logs out. Switch to
  `localStorage` if you want sessions to persist.

## Batch (non-live) transcription

`soniox_client.transcribe_file(path)` uploads a `.wav`/`.mp3` and returns merged
speaker turns using the async API, which has full-file context and is more
accurate than the live path. Exposed at `POST /api/transcribe` (authenticated).