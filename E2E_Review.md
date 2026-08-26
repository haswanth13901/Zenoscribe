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

`.github/workflows/ci.yml` runs six jobs on every push: **backend-lint**
(`flake8`), **backend-fast** (`pytest -q`), **backend-integration** (the full
`test_e2e_playwright_*.py` suite), **frontend-unit** (Vitest), **docker-build**
(builds the production image, sanity-checks it runs non-root with no leaked
`.env` file, then runs a Trivy scan against the built image and fails on any
`CRITICAL`/`HIGH` vulnerability), and **dependency-audit** (`pip-audit` on
`requirements.txt`, `npm audit` on the frontend). `.github/dependabot.yml`
separately opens weekly version-bump PRs across pip, npm, the Dockerfile base
image, and the workflow's own GitHub Actions.

## Open items

1. **Multi-instance scale — fixed (2026-08-25).** The three things that used
   to assume a single process are addressed: (a) recording storage now goes
   through `voice_transcriber/storage/`, with a required MinIO backend in
   production instead of a local volume; (b) `SERVER_BOOT_ID` (`auth.py`) is
   now a required, shared production value instead of a per-process random
   one; (c) rate limiting (`rate_limit.py`) is now Redis-backed instead of
   an in-memory counter. Full detail, verification status (what was run
   against real Postgres/fakeredis here vs. what needs a real multi-replica
   Docker Compose run on a VM with Docker available), and remaining
   single-points-of-failure (Postgres/Redis/MinIO/the VM itself are each
   still one instance - only `web` is now horizontally scalable) live in
   `SCALABILITY_AUDIT.md`, `SCALABILITY_DESIGN.md`, and
   `HORIZONTAL_SCALABILITY_READINESS.md`.
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
