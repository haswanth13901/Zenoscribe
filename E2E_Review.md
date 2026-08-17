# Zenoscribe — E2E Review (2026-08-17)

## What this project is

Live speech transcription and translation web app. FastAPI + Postgres backend;
hybrid frontend — the login page is plain vanilla JS/HTML, everything
post-login is a React + Redux Toolkit SPA served by the same FastAPI process.

Five feature pages plus an admin console:

- **Recorder** (`/app`) — live mic transcription. Raw PCM streams over a
  WebSocket to Soniox via an `AudioWorklet`; turns are segmented by
  speaker/pause.
- **Translate** (`/translate`) — same live pipeline, two-way: transcribes and
  translates in real time, with optional spoken-aloud TTS playback.
- **Upload** (`/upload`) — batch mode: transcribe/translate an existing audio
  file without a live session.
- **My recordings** (`/recordings`) — history of your own sessions, tagged by
  source (transcribe/translate/upload), with transcript/audio download.
- **Admin console** (`/admin`) — user management plus a cross-user view of
  all recordings.

Auth is custom JWT + bcrypt, no cookies — token lives in `sessionStorage` and
clears on tab close. Postgres is the real datastore (not SQLite), Alembic
migrations auto-apply on startup.

## Deployment readiness — findings and fixes

| Issue | Status |
|---|---|
| No `$PORT` env support — hardcoded `:8000` everywhere | **Fixed** — `Dockerfile` and `docker-compose.yml` now bind `${PORT:-8000}` |
| `docker-compose.yml` bind-mounted the whole repo, shadowing the image's built `frontend/dist/` | **Fixed** — now only bind-mounts backend source (`voice_transcriber/`, `alembic/`, `scripts/`); frontend build stays intact |
| Stale, unused SQLite `app.db` leftover from pre-Postgres era | **Fixed** — deleted (was gitignored, untracked) |
| CI only ran 1 of 6 Playwright integration tests, and never ran the fast pytest suite or the frontend Vitest suite | **Fixed** — see CI section below |
| Recordings stored on local container disk, no object storage | **Open** — needs an infra decision (S3/GCS + credentials) before it's safe on any host with an ephemeral filesystem |
| Local `.env` has live-looking secrets, `ALLOW_TEST_HOOKS=true` | **Open** — rotate before any `.env` reaches production |
| HTTPS/TLS entirely on the deployer | **Open by design** — required anyway since mic capture needs a secure context |

## Mobile / any-device readiness — findings and fixes

| Issue | Status |
|---|---|
| Translate TTS playback silently produced no audio on iOS Safari (`AudioContext` created off an async WS callback, never resumed) | **Fixed** — `useTranslateConnection.ts`: context now created + `.resume()`d synchronously inside the click handler; also fixed a related pitch-distortion risk (buffer now declares the source's real sample rate, not the context's, letting the browser resample) |
| Sidebar was a fixed 190px column that ate real width on a phone | **Fixed** — below 720px it's now an off-canvas overlay drawer: starts collapsed, opens over content with a tap-to-close backdrop, auto-closes on navigation |
| Admin/recordings tables broke layout or squeezed unreadably on narrow screens | **Fixed** — tables scroll horizontally below 720px instead |
| Recorder/Translate toolbars could overflow horizontally on narrow screens | **Fixed** — added `flex-wrap` |
| `matchMedia` used in `AppLayout` without guarding for environments that lack it (jsdom test env, very old browsers) | **Fixed** — guarded with a feature check; verified all 190 Vitest tests still pass |
| Live audio capture already used `AudioWorklet` + raw PCM instead of `MediaRecorder` | **Already solid** — avoids Safari's flaky `MediaRecorder` codec support |

## CI — findings and fixes

Old `.github/workflows/playwright-e2e.yml` ran exactly one test file
(`test_e2e_playwright_upload.py -m integration`) and nothing else.

Replaced with `.github/workflows/ci.yml`, three parallel jobs:

- **backend-fast** — `pytest -q`, the ~20-file isolated unit/API suite (was
  never run in CI before). Needs the frontend built first too, since some of
  these tests assert on the real built `index.html`.
- **backend-integration** — `pytest voice_transcriber/tests -m integration
  -q`. All six `test_e2e_playwright_*.py` files carry the `integration`
  marker; the old job only ran one of them. Broadened to the whole dir — 19
  integration tests now run instead of 2.
- **frontend-unit** — `npm --prefix frontend test` (Vitest), wasn't wired
  into CI at all before.

Also removed dead config: `TEST_HOOK_SECRET` and `ALLOW_TEST_HOOKS` were set
at the job level but nothing read them there — the `live_server` fixture
that launches the test server always sets its own copies on the subprocess
directly. Verified: all 19 integration tests pass with both fully unset.

**Verified locally** (against a local Postgres matching the CI service
container's credentials): 69/69 fast tests pass, 19/19 integration tests
pass, 190/190 Vitest tests pass, and `npm run build` (tsc + vite) succeeds
clean.

## Left over — needs a decision, not more code

1. **Recordings storage durability** — audio files live on local disk, no
   object storage. Lost on restart on any ephemeral-filesystem host, breaks
   multi-instance scaling. Needs an S3/GCS (or similar) decision + credentials.
2. **Secret rotation** — local `.env` has live-looking values (Soniox key,
   JWT secret, admin password) and `ALLOW_TEST_HOOKS=true`. Rotate before
   any `.env` reaches production; keep `ALLOW_TEST_HOOKS=false` there.
3. **Backgrounding / lock-screen behavior** — mobile browsers suspend JS/audio
   when a tab backgrounds or the phone locks mid-recording; nothing detects
   this today. A live session can die silently. Worth a `visibilitychange`
   handler that at least warns the user.
4. **WebSocket reconnection** — a dropped connection (common on cellular)
   currently just tears the session down. Reconnect-with-backoff would make
   this usable off wifi.
5. **PWA basics** — no manifest/service worker. Would enable home-screen
   install and a real offline-capable shell.
6. **Browser support floor** — `AudioWorklet` needs iOS Safari 14.5+ /
   modern Chromium/Firefox. No detection or messaging for anyone below that;
   they just hit a silent failure today.
7. **Large-screen underuse** — layout maxes out readable width but doesn't
   take advantage of ultrawide monitors or split-screen tablet use (e.g.
   Translate's columns view).
8. **Real-device testing** — everything above was verified via code reading,
   a production build, and automated suites, not an actual iPhone/Android in
   hand. Worth a real-device pass before calling mobile support done.
