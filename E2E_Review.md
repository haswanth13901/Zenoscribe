# Zenoscribe — E2E Review

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

## CI

`.github/workflows/ci.yml` runs three jobs on every push: **backend-fast**
(`pytest -q`), **backend-integration** (the full `test_e2e_playwright_*.py`
suite), and **frontend-unit** (Vitest).

## Open items

1. **Multi-instance scale — three things assume a single process today.**
   Fine for a single container (a named Docker volume covers recordings —
   see README's Production section). If this ever runs as more than one
   instance at once (load-balanced replicas, etc.), all three need
   revisiting: (a) a local volume isn't shared across instances, needs
   S3-compatible object storage; (b) `SERVER_BOOT_ID` (`auth.py`) is
   generated per-process, so sessions randomly invalidate when a request
   lands on a different instance; (c) rate limiting (`rate_limit.py`) is an
   in-memory counter per-process, so a per-user limit effectively multiplies
   by instance count instead of being enforced globally (a user could get N×
   their intended quota by getting round-robined across N instances - not a
   security hole on its own, just a soft cap that stops being precise).
   Revisit if/when real scale needs come up — not worth building ahead of
   that.
2. **Secret rotation.** Code-side guards exist (production refuses to boot
   on a missing/weak `DATABASE_URL`/`JWT_SECRET`/`ADMIN_PASSWORD`, or with
   `ALLOW_TEST_HOOKS=true`). What's left is manual: rotate the live Soniox
   key, generate a fresh `JWT_SECRET` and strong `ADMIN_PASSWORD`, and put
   them in `.env.production` or your platform's secret store — never in a
   committed `.env`. Tracked as a checklist in `DEPLOYMENT.md` for the
   deploy team.
3. **Real-device testing.** Everything mobile-related has been verified via
   code, automated suites, and a production build — not an actual
   iPhone/Android in hand. Worth a real-device pass before calling mobile
   support done.
4. **HTTPS/TLS** — on the deployer, by design. Required anyway, since mic
   capture needs a secure context.
