# Zenoscribe — Deployment Readiness Audit

**Verdict: GO WITH CONDITIONS**

The fail-closed production guards, ownership checks, rate limiting, and the Caddy/Docker network topology all hold up under direct code and runtime inspection — this is a materially more careful pre-launch codebase than most, and its own `DEPLOYMENT.md`/`E2E_Review.md` already document several of the trade-offs an audit would normally have to discover. The one real architectural gap is that almost the entire database layer is synchronous `psycopg_pool` code called directly from `async def` route handlers with `--workers 1`, so any HTTP request (including the two-line `current_user` dependency that runs on nearly every API call) blocks the single event loop that also drives every live WebSocket audio session. Nothing here causes data loss or an auth bypass, so it doesn't block shipping, but it should be fixed the same week, and disk-growth monitoring must be wired up before go-live since the recordings volume has no retention policy and this app writes ~115MB/hour of WAV per concurrent live session.

---

## Status update (2026-08-22)

Fixed since this audit was written. Everything below this section is left
exactly as originally reported — evidence, file:line citations, and all — as
a historical snapshot against the audited commit; `DEPLOYMENT.md` §5 carries
the evergreen, currently-maintained status instead of this doc (see that
file's rationale for why the two are kept separate).

- **P1-1 / P1-2 (blocking DB/bcrypt calls on the single event loop) — Fixed.**
  Every direct `db.*` call in `routes_api.py` and in `auth.py`'s
  `current_user`/`user_from_token`/`user_from_ws`, every
  `bcrypt.hashpw`/`checkpw` call site, and `translate.py`'s WS auth path
  (which had the same unwrapped `auth.user_from_token` call but wasn't
  named in the original P1-1 evidence list) now run through
  `asyncio.to_thread`, matching the pattern `transcribe.py` already used.
  Verified: full `pytest -q` suite (81 passed, 21 deselected) green post-fix.
- **P1-3 (recordings disk growth monitoring) — still open, operational.**
  No code fix applies here by design (see the finding's own "smallest fix");
  tracked as a pre-go-live task in `DEPLOYMENT.md` §3.
- **P2 — WebSocket auth has no timeout on the first frame — Fixed.**
  `auth.user_from_ws` (used by `transcribe.py`) and `translate.py` both now
  wrap the first `receive_json()` in `asyncio.wait_for(..., timeout=10)`.
- **P2 — unrelated repo content ships inside the production image — Fixed.**
  `.dockerignore` now excludes `voice_transcriber/tests/` and
  `voice_transcriber/code_reviews/`.
- **P2 — no lint/type-check CI gate — Fixed.** A new `backend-lint` job runs
  `flake8` as a blocking gate; the CI job count cited in that finding below
  (5 jobs) is now 6. The 45 pre-existing `flake8` violations it caught were
  fixed first so the gate starts green, not red.
- **P2 — no container/base-image scan, no Dependabot — Fixed.** CI's
  `docker-build` job now runs `aquasecurity/trivy-action` against the built
  image (`CRITICAL,HIGH`, `exit-code: 1`, `ignore-unfixed: true`), and
  `.github/dependabot.yml` opens weekly bump PRs for pip, npm, the Dockerfile
  base image, and GitHub Actions. CodeQL/SAST and an SBOM remain open,
  lower-urgency backlog.
- **P2 — no image registry / no git tags yet — still open** (git tagging is
  also in the Gate checklist, §6 of `DEPLOYMENT.md`). Tracked in
  `DEPLOYMENT.md` §3.
- **P2 — `/healthz` degradation has no automated remediation — unchanged.**
  Still accurate as written; `DEPLOYMENT.md` §3 now calls out the specific
  mechanism (restart policy triggers on exit, not on failed healthcheck) so
  it isn't missed when wiring up monitoring.
- **Notes — `@app.on_event` deprecation — unchanged**, still a same-effort,
  no-risk cleanup whenever convenient, not launch-relevant.

---

## P0 blockers

**None found.** No auth bypass, no secret exposure in logs, no data-loss path, and no guaranteed-outage-in-week-one scenario turned up under direct tracing. See P1s below for the two items that should still be closed out promptly.

---

## P1 — fix this week, with a written mitigation until then

### P1-1. Nearly the entire DB layer runs synchronous psycopg calls directly on the async event loop

**Evidence:**
- [db.py:15](voice_transcriber/db.py#L15), [db.py:32-38](voice_transcriber/db.py#L32-L38) — `from psycopg_pool import ConnectionPool` (the **sync** pool; psycopg_pool also ships an `AsyncConnectionPool` that isn't used anywhere in this repo).
- `.venv/Lib/site-packages/psycopg_pool/pool.py:172` — `def connection(...) -> Iterator[CT]` confirms `ConnectionPool.connection()` is a blocking, non-async context manager.
- [auth.py:134](voice_transcriber/auth.py#L134) — `db.touch_seen(row["id"])` called directly inside `async def current_user`, the dependency nearly every `/api/*` route declares.
- [auth.py:104](voice_transcriber/auth.py#L104) — `row = db.get_user(payload.get("sub"))` inside `user_from_token`, called from the same dependency.
- [routes_api.py:93-102](voice_transcriber/routes_api.py#L93-L102) — `async def login` makes **four** sequential sync DB calls (`count_recent_failed_logins`, `get_user_by_username`, `record_failed_login`/`clear_failed_logins`, `touch_login`) plus a sync `bcrypt.checkpw` (see P1-2), none wrapped in `asyncio.to_thread`.
- Every other route in `routes_api.py` (`list_recordings`, `get_transcript`, `get_audio`, `remove_recording`, all `/api/admin/*` routes) calls `db.*` the same direct, unwrapped way.

Contrast this with `transcribe.py`/`translate.py`, which *do* wrap every DB and file call in `asyncio.to_thread` (`async_touch_seen`, `async_add_recording`, `async_write_text`, `async_get_wav_duration` — [transcribe.py:69-101](voice_transcriber/transcribe.py#L69-L101)) — the live-session code paths got this right; the HTTP API paths did not.

**Failure scenario:** With `--workers 1` (deliberately pinned — [Dockerfile:62-69](Dockerfile#L62-L69)), there is exactly one asyncio event loop for the whole process. While any coroutine is inside a synchronous `db.<call>()`, that thread cannot run any other coroutine, including the `pump_audio`/`pump_results`/`watchdog` tasks of every live `/ws` and `/ws/translate` session. A user polling `/api/recordings`, an admin loading `/api/admin/users`, or simply another user logging in, each blocks the event loop for a real Postgres round-trip; `/api/login` alone does four such round-trips plus a ~200-300ms bcrypt hash (P1-2). During that window, every other live recording/translation session on the box stalls — audio frames queue up in `write_queue` rather than being written or forwarded, which is the exact "single blocking call stalls every live WebSocket" scenario this deployment's own Dockerfile comment (line 62-69) warns `--workers 1` requires being careful about.

**Smallest fix:** Wrap the direct `db.*` calls in `routes_api.py` and the two calls in `auth.py`'s `current_user`/`user_from_token` in `asyncio.to_thread(...)`, exactly as `transcribe.py` already does. This is a mechanical, low-risk change (no schema/behavior change) — the pattern to copy already exists in the same repo.

### P1-2. `bcrypt` password hashing/verification runs synchronously on the event loop

**Evidence:** [auth.py:64-72](voice_transcriber/auth.py#L64-L72) — `hash_password`/`verify_password` call `bcrypt.hashpw`/`bcrypt.checkpw` directly (no `to_thread`); called from [routes_api.py:96](voice_transcriber/routes_api.py#L96) (`login`), 161 (`admin_create_user`), 184 (`admin_reset_password`), all inside `async def` handlers.

**Failure scenario:** `bcrypt.gensalt()`'s default cost factor (12) makes each hash/verify take roughly 150-300ms on typical VM hardware. Every login blocks the sole event loop for that entire window — same mechanism as P1-1, worse magnitude (CPU-bound, not I/O-bound, so it can't even be shortened by DB latency). Two people logging in in quick succession during someone else's live recording is a plausible, not edge-case, scenario.

**Smallest fix:** Wrap the three call sites in `asyncio.to_thread`, or fold `bcrypt` calls into the same executor already built for uploads (`_UPLOAD_EXECUTOR` in [routes_api.py:51-53](voice_transcriber/routes_api.py#L51-L53) — though a dedicated small pool is safer, since bcrypt is CPU-bound and would otherwise compete with upload transcription for the same 3 threads).

### P1-3. Unbounded recordings disk growth has no automated monitoring, only a documented manual watch

**Evidence:** [transcribe.py:142-145](voice_transcriber/transcribe.py#L142-L145) — 16kHz, 16-bit, mono PCM WAV (`setframerate(16000)`, `setsampwidth(2)`, `setnchannels(1)`) ⇒ 32,000 bytes/sec ⇒ **~115MB per concurrent live-session hour**, before translate.py's identical capture or upload-flow storage. `DEPLOYMENT.md` §3 already says this out loud ("Recordings and WAV files grow without bound... Watch disk usage on the VM") and §7/README don't wire up any automated check — no cron, no disk-usage alert, no per-user quota, no retention job anywhere in `scripts/` (`reconcile_recordings.py` only reconciles DB/file drift, it doesn't delete for space).

**Failure scenario:** A handful of hours of daily live usage is a few hundred MB-to-low-GB per day; on a modest VM this fills the disk within weeks, at which point Postgres (`pgdata` on the same disk unless split) can't write WAL and `recordings/` writes fail mid-session — the worst-case outcome (silent data loss on `wave.open()`/`writeframes` failures, which are currently caught broadly and logged, not surfaced to the user) rather than a clean, alertable failure.

**Smallest fix:** This doesn't need a code change to ship — it needs an operational one before go-live: put a disk-usage alert (e.g. `df` threshold via any uptime/monitoring tool already in use) on the VM, sized against actual expected concurrent-usage hours. Treat this as a pre-deploy checklist item, not a merge blocker.

---

## P2 — backlog

- **No lint/type-check CI gate.** `flake8`/`black` are pinned in [requirements-dev.txt:33-34](requirements-dev.txt#L33-L34) but [.github/workflows/ci.yml](.github/workflows/ci.yml) has no job that runs either — confirmed by reading the file end to end (5 jobs: `backend-fast`, `backend-integration`, `frontend-unit`, `docker-build`, `dependency-audit`; none invoke `flake8`/`black`). Style drift isn't a launch risk, but it's a one-line CI addition worth doing before it costs a real review cycle.
- **No container/base-image scan, no CodeQL, no Dependabot, no SBOM.** Confirmed: `.github/` contains only `workflows/ci.yml` (`find .github -type f`), and there is no `.github/dependabot.yml` or CodeQL workflow anywhere in the tree. `pip-audit`/`npm audit` (present) cover known-vuln Python/JS *packages*; they don't cover the `python:3.12-slim` base image itself. Worth adding a Trivy (or equivalent) step to `docker-build`, and a Dependabot config for version-bump PRs, but neither is an auth/data-safety gap.
- **Unrelated repo content ships inside the production image.** [.dockerignore](.dockerignore) excludes `.git/`, `.github/`, Python/Node build artifacts, `.env*`, and `voice_transcriber/recordings/` — but **not** `voice_transcriber/tests/` (805KB), `voice_transcriber/code_reviews/` (28KB of internal review notes — spot-checked [Review-1.md](voice_transcriber/code_reviews/Review-1.md), no secrets found, just prose critique of the codebase), `scripts/` (20KB), `alembic/` (41KB, though this one is arguably needed at runtime since `db.init()` calls `alembic.command.upgrade` against `alembic.ini` — see [db.py:53](voice_transcriber/db.py#L53)), or the three root markdown docs (~52KB combined). Total unnecessary bloat is under 1MB — not a size problem — but `code_reviews/` in particular is internal commentary about the codebase's own weak points; shipping it into every running container is a minor information-disclosure surface if a container is ever compromised. Recommend excluding `voice_transcriber/tests/` and `voice_transcriber/code_reviews/` at minimum; `alembic/` should stay.
- **No image registry / no git tags yet.** `docker-compose.prod.yml` uses `build: .`, and `git tag` currently returns zero tags (55 commits of real, non-squashed history — the audit brief's premise of "a single squashed commit" does **not** hold; `git log` shows granular, well-described commits). `DEPLOYMENT.md`'s own rollback runbook (§2, "Rollback") already describes checking out the previous release's code and rebuilding, which works today, but "rollback" currently means a full `docker build` (frontend `npm ci`+`npm run build`, backend `pip install`), not an instant image swap. The gate checklist in DEPLOYMENT.md §5 already says to "tag the release you deploy" — actually doing that (git tag per deploy, and ideally pushing built images to a registry) would make rollback both faster and less error-prone during an incident.
- **WebSocket auth has no timeout on the first frame.** [transcribe.py:41-48](voice_transcriber/transcribe.py#L41-L48) and [translate.py:54-62](voice_transcriber/translate.py#L54-L62) both `accept()` the socket, then `await ...receive_json()` for the auth frame with no timeout. An unauthenticated client that connects and never sends a frame holds an open socket + suspended task indefinitely. Bounded in practice by `GlobalRateLimitMiddleware`'s per-IP cap (600 req+WS/60s — [rate_limit.py:97](voice_transcriber/rate_limit.py#L97)) and by normal OS/uvicorn connection ceilings, so this is a nuisance-level slow-resource-hold, not an unauthenticated-DoS with no backstop. A `asyncio.wait_for(..., timeout=10)` around the first `receive_json()`/`receive()` call in both files would close it off cheaply.
- **`/healthz` degradation has no automated remediation.** [server.py:188-200](voice_transcriber/server.py#L188-L200) correctly returns 503 when `db.ping()` fails, and the Compose healthcheck ([docker-compose.prod.yml:67-72](docker-compose.prod.yml#L67-L72)) will mark `web` unhealthy — but Docker's `restart: unless-stopped` policy triggers on container *exit*, not on healthcheck status, so a sustained DB outage leaves `web` running and serving 503s/500s rather than being cycled or triggering any alert. Caddy also doesn't consult container health; it just proxies to `web:8000` regardless. This matches `DEPLOYMENT.md` §3's ask for external monitoring against `/healthz` — that monitoring needs to actually exist operationally (Unverified — see below), since nothing in the stack self-heals this.

---

## Notes

- **`SERVER_BOOT_ID`/`ADMIN_PASSWORD` nuances are accurately documented, not drift.** The audit brief's framing ("auth.py hard-fails on missing ADMIN_PASSWORD") is a simplification of what the code actually does — `ensure_seed_admin()` ([auth.py:163-198](voice_transcriber/auth.py#L163-L198)) only enforces the password-strength guard when `db.count_admins() == 0`, i.e. first boot only, and `SERVER_BOOT_ID` regenerates on every restart unless pinned. Both nuances are called out correctly and prominently in `DEPLOYMENT.md`'s variable table and `.env.production.example`'s inline comments — this is one of the areas where the docs are *more* precise than a shorthand summary of them would suggest, not less.
- **X-Forwarded-For spoofing was traced end-to-end and is not exploitable as configured.** `--forwarded-allow-ips="*"` ([Dockerfile:70-77](Dockerfile#L70-L77)) makes uvicorn's `ProxyHeadersMiddleware` trust the *first* entry in any `X-Forwarded-For` header it receives (confirmed by reading `_TrustedHosts.get_trusted_client_address` in `.venv/Lib/site-packages/uvicorn/middleware/proxy_headers.py:169-187`: `always_trust` ⇒ return `x_forwarded_for_hosts[0]`, i.e. the leftmost/attacker-nearest entry, not the rightmost/proxy-nearest one). That sounds spoofable — except the `Caddyfile` in this repo has no `trusted_proxies` global option set, and Caddy's documented default (confirmed via caddyserver.com docs) is to **discard any inbound `X-Forwarded-For` value from the client** and set a fresh header containing only the IP it observed directly. So the only `X-Forwarded-For` value uvicorn ever sees is one Caddy generated itself from the real TCP connection — a client cannot influence it. This closes the loop the audit brief flagged (`failed_logins`/rate-limit buckets keying off a spoofable IP) as a non-issue *for this specific Caddy version and config*; it would become exploitable only if `trusted_proxies` were later added to the Caddyfile for a CDN/upstream proxy without re-verifying this chain.
- **Ownership/authorization checks are consistent and correctly fail closed to 404.** Every recording route (`get_transcript`, `get_audio`, `remove_recording`) goes through `_authorize_recording()` ([routes_api.py:325-332](voice_transcriber/routes_api.py#L325-L332)), which 404s (not 403s) on a mismatched `user_id`, deliberately avoiding ID-enumeration. `rec_id` is only ever used as an exact-match DB lookup key, never string-concatenated into a filesystem path, and the filename actually opened (`row["wav_file"]`/`row["txt_file"]`) comes from the DB row, not from user input — no path-traversal vector. Every `/api/admin/*` route requires `Depends(auth.current_admin)` server-side ([routes_api.py](voice_transcriber/routes_api.py), all admin routes); the frontend's `RequireAuth adminOnly` is confirmed to be a UX convenience layered on top of this, not the enforcement mechanism.
- **Boot-time secret guards genuinely run before the app can serve traffic.** `config.py`'s `DATABASE_URL`/`SONIOX_API_KEY`/`ALLOW_TEST_HOOKS` checks ([config.py:38-39](voice_transcriber/config.py#L38-L39), 46-47, 107-108) and `auth.py`'s `JWT_SECRET` check ([auth.py:35-39](voice_transcriber/auth.py#L35-L39)) are module-level code that raises `RuntimeError` at **import time**, before `server.py` ever constructs the `FastAPI()` app or uvicorn binds a socket — these are architecturally earlier than the `@app.on_event("startup")` handler, not inside it. The `ADMIN_PASSWORD` guard is the one exception, correctly scoped to first-boot only (see above).
- **`@app.on_event` is deprecated but functional — confirmed, not assumed.** Running `python -m pytest -q` surfaces the exact `DeprecationWarning` at [server.py:81](voice_transcriber/server.py#L81) and 99 ("on_event is deprecated, use lifespan event handlers instead"). `fastapi==0.141.1` still supports it; there's no indication of a near-term removal in this test run. Migrating to `lifespan=` is a same-effort, no-risk cleanup whenever convenient — not launch-relevant.
- **Migrations auto-apply on every boot with no advisory lock — a non-issue for this specific deployment.** `db.init()` ([db.py:50-54](voice_transcriber/db.py#L50-L54)) calls `alembic upgrade head` unconditionally on every process start with no `pg_advisory_lock`. This would matter if multiple `web` instances/workers started concurrently against the same DB, but `--workers 1` and the documented single-container topology (`DEPLOYMENT.md` §4) mean there is only ever one process doing this at a time in the shipped deployment. A failed migration mid-upgrade would fail the startup event, uvicorn would exit non-zero, and `restart: unless-stopped` would crash-loop until the underlying migration/DB problem is fixed manually — DEPLOYMENT.md §2 already documents this as accepted (no manual approval gate) and recommends testing against a staging DB copy first.
- **No secret leakage found in logging paths.** Grepped every `log.*` call across `voice_transcriber/` for token/password/secret/api_key content; the only matches are guard messages that name *which* variable is missing/weak (e.g. "JWT_SECRET not set"), never the value. `translate.py`'s `DEBUG_TOKENS` gate ([translate.py:294-306](voice_transcriber/translate.py#L294-L306)) correctly defaults to logging only a redacted length when off, and `config.py`/`.env.production.example` both correctly default `DEBUG_TOKENS=false`.

---

## Verified working

- Full fast test suite: `python -m pytest -q` → **81 passed, 21 deselected** (integration/real-network tests correctly excluded by `pytest.ini`'s default `-m "not integration and not real_network"`), 101s.
- Boot-guard code paths for `DATABASE_URL`, `SONIOX_API_KEY`, `ALLOW_TEST_HOOKS`, and `JWT_SECRET` traced to confirm they execute at module-import time, before the ASGI app or uvicorn socket exist.
- `X-Forwarded-For` trust chain traced end-to-end across uvicorn's `ProxyHeadersMiddleware` source and Caddy's documented default behavior (no `trusted_proxies` configured in this repo's `Caddyfile`) — not spoofable as shipped.
- Recording ownership checks (`_authorize_recording`), admin-route gating (`current_admin`), and no-path-traversal-via-`rec_id` traced through `routes_api.py`.
- `psycopg_pool.ConnectionPool.connection()` confirmed synchronous by reading the installed package source directly (not assumed from the package name).
- Test-hook endpoint (`/internal/test-hook/transcribe_mode`) confirmed to require all three of: `ALLOW_TEST_HOOKS` (hard-disabled in production by a separate `config.py` guard), an optional shared secret, and localhost restriction — all three checked independently, not an either/or.
- No `dangerouslySetInnerHTML`/`innerHTML`/`document.write` anywhere under `frontend/src` (grepped directly).
- No secret values (only variable *names*) appear in any `log.*` call across the backend.
- `.dockerignore` correctly excludes `.env*` and `voice_transcriber/recordings/`; CI's `docker-build` job independently re-verifies no `.env` file lands in the built image on every push.
- Git history is 55 real, individually-described commits — not a single squashed commit as the audit brief assumed.

## Unverified / needs access

- **Docker build and a live `docker-compose.prod.yml` run.** This environment has no `docker` CLI available (`docker: command not found`), so the image was not built here and the stack was not brought up against a throwaway `.env.production`. What would settle it: run `docker build -t zenoscribe:audit .` and record image size/`whoami`/`ls -a /app`; then `docker compose --env-file .env.production.test -f docker-compose.prod.yml up -d --build` and confirm `/healthz`, security headers, port 8000 unreachable from the host, and a live user-A-fetches-user-B's-recording negative test. CI's `docker-build` job already does the image-build half of this on every push, which is meaningfully reassuring but not a substitute for a local run against this exact working tree.
- **Actual VM disk size and expected concurrent-usage volume.** The ~115MB/hour/session figure is derived from the WAV format constants in code; whether that fills a real disk in days or months depends on the target VM's disk size and actual usage pattern, neither of which is knowable from the repo.
- **Whether any external monitoring is actually watching `/healthz` and disk usage today.** `DEPLOYMENT.md` asks the deploy team to set this up; nothing in the repo can confirm it exists. Settle by asking the deploying team directly, or checking whatever monitoring platform they use.
- **Real dependency versions vs. currently-known CVEs** for the pinned versions in `requirements.txt`/`frontend/package.json` — CI's `pip-audit`/`npm audit` jobs cover this on every push and are the authoritative source; re-running them here would only duplicate that, not add information.
- **Mobile real-device behavior** — `E2E_Review.md` and `DEPLOYMENT.md` both already flag this as unverified on real hardware; nothing in this audit changes that.

---

## Pre-deploy checklist

```bash
# 1. Fresh clone, confirm nothing depends on local/dev state
git clone <repo-url> zenoscribe-deploy && cd zenoscribe-deploy
cp .env.production.example .env.production
# fill in: POSTGRES_PASSWORD, SONIOX_API_KEY (a fresh production key, not dev's),
#          JWT_SECRET (python -c "import secrets; print(secrets.token_urlsafe(48))"),
#          ADMIN_PASSWORD (strong, >=8 chars), SERVER_BOOT_ID (pin it, or accept
#          that every restart logs everyone out - decide this deliberately)

# 2. Prove the production guards actually fire (DEPLOYMENT.md's own gate item)
#    Temporarily blank JWT_SECRET in .env.production and confirm the container
#    refuses to start, then restore it.

# 3. Build and bring up
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build

# 4. Confirm the image contents match expectations
docker run --rm $(docker compose -f docker-compose.prod.yml images -q web) ls -a /app
#   -> only .env.example / .env.production.example, no real .env

# 5. Confirm port 8000 is not reachable from the host
curl -m 3 http://127.0.0.1:8000/healthz   # should fail to connect (only Caddy can reach it)

# 6. Put the real domain in Caddyfile before this step (mic capture needs a secure
#    context - localhost doesn't count for a real deploy)
#    Confirm DNS points at the VM, then re-check step 3's `up` picked up the change.

# 7. Set up disk-usage alerting on the VM NOW (P1-3) - before real traffic, not after
#    e.g. a df-threshold check via whatever uptime/monitoring tool is already in use.

# 8. Set up external monitoring against GET /healthz (DEPLOYMENT.md §3)

# 9. Full test suite green on the exact deployed commit
python -m pytest -q
npm --prefix frontend run build
npm --prefix frontend test

# 10. Tag the release
git tag deploy-$(date +%Y%m%d) && git push --tags   # only if the user wants this pushed

# --- Post-deploy smoke test (over the real HTTPS domain, not localhost) ---
# a. Log in as the seeded admin; confirm the login page loads over TLS with the
#    security headers present:
curl -sI https://your-domain.example.com/ | grep -Ei 'strict-transport|x-frame|x-content-type|content-security'
# b. Create one real user via the admin console.
# c. As that user: start a live recording, speak a sentence, stop it, confirm the
#    transcript appears in "My recordings" and the audio file downloads.
# d. As that user: try /translate one-way for a few seconds; confirm captions and
#    (if enabled) spoken TTS playback work.
# e. As that user: upload a short audio file via /upload; confirm it returns turns
#    and shows up in "My recordings" tagged source=upload.
# f. Negative auth check: as a second user, try GET /api/recordings/{first user's
#    recording id}/audio - must be 404, not the file.
# g. GET https://your-domain.example.com/healthz -> {"status":"ok","database":"ok"}
```

---

## If you scale beyond one container

Kept separate from the verdict above per this audit's scope — these are already accurately documented in `E2E_Review.md`'s "Open items" §1 and not launch risks for the single-VM/`--workers 1`/single-container deployment this repo actually ships:

- **Recordings storage** is a local named Docker volume; a second replica can't see the first's files. Needs S3-compatible object storage before any horizontal scale.
- **`SERVER_BOOT_ID`** is generated per-process; multiple instances would each mint their own, so a session would randomly 401 depending on which instance handled a given request. Needs a shared value (e.g. injected via the deploy pipeline) or a shared session-validity store.
- **`rate_limit.py`** counters are an in-memory `dict` per process ([rate_limit.py:1-8](voice_transcriber/rate_limit.py#L1-L8), explicitly commented as such) — multiple instances multiply a user's effective quota by instance count rather than enforcing one global limit. Not a security hole per se (still bounded), just an imprecise cap. Needs Redis or equivalent shared state to stay precise at scale.
- **`--workers 1` is load-bearing**, not just a default — raising it without addressing `SERVER_BOOT_ID` and concurrent-migration-on-startup first would reintroduce both problems inside a single container, before even reaching multi-container concerns.
