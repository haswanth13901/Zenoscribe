# Zenoscribe — Horizontal Scalability Readiness (Phase 7)

*Audited against the working tree as of this pass (2026-08-25), branch
`main`, on top of commit `bf64f72`. Nothing in this pass has been
committed — review the diff and commit deliberately.*

**Verdict: READY FOR STAGING**

Not "PRODUCTION READY": the architecture, code, and unit/integration-level
tests are complete and genuinely verified against a real local Postgres and
a real Lua-executing Redis stand-in (fakeredis) — not asserted on faith.
But the multi-replica, multi-container, and real-SIGTERM behaviors that
only a live Docker Compose stack can prove are **UNVERIFIED** — this tool
environment has no Docker, Redis server, or MinIO server available (see
`SCALABILITY_AUDIT.md`'s environment note). Every such item below is marked
explicitly. Run the "Required before production" checklist at the bottom on
your VM before calling this production-ready.

---

## A. What changed and why

Three real horizontal-scaling blockers existed, all previously
self-documented in this repo's own `E2E_Review.md`/`DEPLOYMENT_READINESS_AUDIT.md`
(a better starting point than a typical audit finds): local-disk recording
storage, in-memory rate limiting, and per-process `SERVER_BOOT_ID`. A fourth,
previously-undocumented blocker was found during this pass's own discovery:
nginx's `proxy_pass` would silently fail to load-balance across
`--scale web=N` replicas even after the first three were fixed. All four are
now fixed. Full discovery/design detail: `SCALABILITY_AUDIT.md`,
`SCALABILITY_DESIGN.md`.

Explicitly **not** built, by design: a job-queue/worker fleet (nothing in
this codebase needs one — see `SCALABILITY_DESIGN.md` §1), Kubernetes,
presigned direct-to-MinIO download URLs (would need to expose MinIO to
browsers), and cross-VM database/Redis/MinIO high availability (see §H).

---

## B. Files changed

**New:**
- `voice_transcriber/storage/__init__.py`, `base.py`, `local.py`, `minio_backend.py` — the `StorageService` abstraction (upload/download/stream/delete/exists/list_keys), a local-disk backend (dev/test default) and a MinIO backend (required in production).
- `voice_transcriber/redis_client.py` — single Redis client factory (mirrors `db.py`'s pool singleton pattern).
- `voice_transcriber/live_sessions.py` — process-local registry of active live WS sessions, used only to drain them on graceful shutdown.
- `voice_transcriber/tests/test_storage.py`, `test_rate_limit.py` (rewritten), `test_live_sessions.py`, `test_healthz.py`, `test_transcribe_persistence.py`, `test_reconcile_recordings.py`, plus additions to `test_migrations.py` and `test_auth_and_users.py`.
- This document, `SCALABILITY_AUDIT.md`, `SCALABILITY_DESIGN.md`.

**Modified:**
- `voice_transcriber/rate_limit.py` — in-memory sliding window → Redis-backed sliding window (Lua script), same public API (`hit`, `per_user`, `reset_all`, `GlobalRateLimitMiddleware`), same semantics (rejected hits don't count, independent per-key windows). New `RateLimiterUnavailable` exception for fail-closed behavior on a Redis outage.
- `voice_transcriber/config.py` — `STORAGE_BACKEND`/`MINIO_*`/`REDIS_URL`/`DB_POOL_MAX_SIZE` added, all fail-closed in production where applicable; `live_scratch_dir()` added.
- `voice_transcriber/auth.py` — `SERVER_BOOT_ID` promoted from optional to a hard production requirement.
- `voice_transcriber/db.py` — `DB_POOL_MAX_SIZE` now configurable; added `get_head_revision()`/`get_current_revision()`/`verify_schema_current()`; `init()`'s docstring clarifies it's no longer auto-invoked by the app.
- `voice_transcriber/server.py` — startup no longer runs migrations (verifies schema instead); shutdown now flips `/healthz` unready immediately and drains active live sessions (`live_sessions.request_shutdown_and_wait`) before closing the DB pool/Redis client.
- `voice_transcriber/transcribe.py`, `translate.py` — recordings write to a local scratch dir during the live session, then upload to storage at session end (`_save_transcribe_session`/`_save_translate_session`, both now directly unit-testable); WS-connect throttling now runs through `asyncio.to_thread` and handles `RateLimiterUnavailable`; sessions register with `live_sessions` and check `stop_requested` in their existing watchdog loops.
- `voice_transcriber/routes_api.py` — recording upload/download/delete routed through `storage.get_storage()` instead of direct `Path`/`FileResponse`; `get_audio` now streams via `StreamingResponse`; new `USERNAME_RE` validation on admin-created usernames (see §F).
- `voice_transcriber/tests/conftest.py` — new `isolated_redis` fixture (fakeredis), wired into the `client` fixture.
- `scripts/reconcile_recordings.py` — rewritten backend-agnostic (works against either storage backend via `storage.list_keys()`/`exists()`).
- `requirements.txt` (+`redis`, `+minio`), `requirements-dev.txt` (+`fakeredis`).
- `frontend/nginx.conf` — `resolver`/`$backend`-based `proxy_pass` (the F7 fix).
- `docker-compose.yml`, `docker-compose.prod.yml` — added `redis`, `minio`, `migrate` services; `web`'s recordings volume removed (nothing durable lands locally any more); `web`'s `stop_grace_period` added.
- `.env.example`, `.env.production.example` — new vars documented.
- `.github/workflows/ci.yml` — `redis` service container added to `backend-integration` (the only job that needs a real Redis; `backend-fast` uses fakeredis in-process).
- `DEPLOYMENT.md`, `README.md`, `E2E_Review.md`, `DEPLOYMENT_READINESS_AUDIT.md` — updated for the new architecture (see each file's own diff for specifics).

---

## C. Architecture before vs. after

```
BEFORE                                    AFTER
                                           
   nginx (TLS)                               nginx (TLS)
       |                                     resolver + $backend
   web:8000                          +-------+-------+-------+
   (single, hardcoded)               web-1   web-2   web-3  (N replicas,
       |                                |       |       |    docker compose
   +---+---+                           +---+---+---+---+    --scale web=N)
   |       |                               |               |
 Postgres  local                       Postgres          Redis
           volume                     (shared)      (rate limits only,
        (recordings,                                 shared, no durable
      NOT shared across                                   data)
         replicas)                            |
                                            MinIO
                                    (recordings, shared across
                                          every replica)

  SERVER_BOOT_ID: random          SERVER_BOOT_ID: required, fixed,
  per process                     same value on every replica

  rate_limit.py: in-memory        rate_limit.py: Redis-backed sliding
  dict, per process                window, shared across replicas

  db.init() runs on every         Migrations: one-shot `migrate` service,
  replica's own startup           runs once before any `web` replica starts
```

---

## D. Scalability blockers found (full detail in `SCALABILITY_AUDIT.md`)

| ID | Blocker | Status |
|---|---|---|
| F1 | Recordings on a local volume, invisible across replicas | **Fixed** — `StorageService`, MinIO backend |
| F2 | `rate_limit.py` in-memory counters, multiply by replica count | **Fixed** — Redis-backed sliding window |
| F3 | `SERVER_BOOT_ID` random per process | **Fixed** — required, shared value |
| F4 | Migrations auto-apply on every replica's own startup, no lock | **Fixed** — explicit one-shot `migrate` step |
| F5 | Hardcoded DB pool size (10) per replica | **Fixed** — `DB_POOL_MAX_SIZE`, documented sizing table (`DEPLOYMENT.md` §5) |
| F6 | Upload thread pool per process | Already safe — no change needed |
| F7 | nginx `proxy_pass` doesn't rebalance across `--scale` replicas | **Fixed** — `resolver`/`$backend` |
| F8 | In-connection WS state | Already safe (WS pinned to one replica for its life, by design) — no change needed |
| — | Graceful shutdown didn't exist for live sessions | **Added** — `live_sessions.py`, bookkeeping-level tested; real-session behavior UNVERIFIED (§G) |
| — | (Found during this pass's own security review, not pre-existing scope) Admin-settable usernames had no charset restriction, reaching storage keys unsanitized | **Fixed** — `USERNAME_RE` + `recording_key()`'s defensive check (§F) |

---

## E. Tests executed (all run for real, in this session, against a real local Postgres and a real Lua-executing fakeredis — not asserted)

```
python -m pytest -q
  131 passed, 21 deselected, 6 warnings in ~90s (run repeatedly - see the
  note below on a flaky-test bug this caught)

python -m flake8 voice_transcriber scripts --max-line-length=120
  clean

npm --prefix frontend run build
  succeeds (dist/index.html, assets built)

npm --prefix frontend test -- --run
  34 test files, 212 tests passed

pip-audit -r requirements.txt
  No known vulnerabilities found

npm --prefix frontend audit --audit-level=high
  found 0 vulnerabilities

docker-compose.yml / docker-compose.prod.yml
  parse as valid YAML (python -c "import yaml; yaml.safe_load(...)"),
  expected services present: db, redis, minio, migrate, web[, nginx, certbot]
```

The 21 deselected tests are the existing `integration`/`real_network`-marked
suites (Playwright E2E, real Soniox network calls) — not run this pass for
the same reason they aren't run by plain `pytest -q` normally; CI's
`backend-integration` job runs them with a real Postgres + (now also) a
real Redis service container. That CI job was updated (added the `redis`
service) but **not executed** — GitHub Actions doesn't run in this local
tool environment; the workflow YAML was reviewed for correctness, not
observed running.

**A real bug caught by running the suite repeatedly, not just once:** the
first version of the Redis rate-limit Lua script disambiguated same-instant
hits with `tostring(now) .. '-' .. tostring(math.random(...))`. Running the
full suite several times surfaced an intermittent failure in
`test_admin_write_rate_limit_then_429` (61 rapid calls, expecting exactly a
429 on the 61st). Root cause, confirmed directly (`time.time()` called 200
times in a tight loop on this Windows machine returned the *same* value all
200 times - real, measured, not assumed): with `now` frequently identical
across rapid calls, two hits could collide on the same ZSET member if
`math.random()` happened to repeat, silently coalescing into one entry and
undercounting the window. Fixed by replacing the random suffix with an
`INCR`-based per-key sequence counter for member uniqueness (guaranteed
distinct regardless of clock resolution or Lua's PRNG) - re-verified with a
targeted stress test (65 calls, identical `now` on every single one) giving
exactly 60 allowed / 5 rejected, then the full suite passed cleanly across
multiple repeated runs. Left in the code as a detailed comment
(`rate_limit.py`) so the reasoning survives past this session.

New test coverage added this pass: `test_storage.py` (17 tests — local
backend against a real filesystem, MinIO backend against a mocked `minio`
client, since no real MinIO server is available here), `test_rate_limit.py`
(rewritten, 9 tests, against real Lua execution via fakeredis — verified
independently that fakeredis actually runs the sliding-window script
correctly, not just basic GET/SET, before relying on it), `test_live_sessions.py`
(5 tests, pure bookkeeping), `test_healthz.py` (3 tests), `test_transcribe_persistence.py`
(5 tests, mirroring the pre-existing `test_translate_persistence.py` pattern),
`test_reconcile_recordings.py` (5 tests), plus migration-verification tests
in `test_migrations.py` and a username-validation test in `test_auth_and_users.py`.

---

## F. Security review of every changed component (task requirement §19)

Reviewed against the specific checklist requested. Findings:

- **Authentication/authorization bypasses, IDOR, cross-user recording
  access**: **PASS, unchanged.** `_authorize_recording()`'s DB-row ownership
  check (`routes_api.py`) still runs before any storage call, on every
  recording route, unchanged by the storage-abstraction refactor — a
  storage key looking like it encodes the owner (`users/{user_id}/...`) is
  never itself the authorization mechanism, exactly as `nginx`'s static-file
  serving already wasn't for the old local-disk layout. `rec_id` is still
  only ever an exact-match DB lookup key.
- **WebSocket authorization**: **PASS, unchanged.** Auth still resolves
  (`user_from_ws`/`user_from_token` via the first frame) before the
  rate-limit check or any session work begins, in both `transcribe.py` and
  `translate.py` — only the rate-limit check's internals changed (now
  Redis-backed, now correctly off the event loop via `asyncio.to_thread`).
- **Path traversal — found and fixed this pass.** Admin-created usernames
  had no charset restriction and become part of every recording's storage
  key (`recording_key()`) and live-session scratch filename. A username
  containing `/`, `\`, or `..` could have broken out of the intended
  directory on the local storage backend. This existed in the pre-change
  code too (the old flat filename scheme embedded the same raw username
  directly into a `Path`), so it is **not newly introduced by this pass**,
  but it was found while reviewing the storage refactor and closed as part
  of it: `routes_api.py`'s `USERNAME_RE` now restricts usernames to
  `[A-Za-z0-9._-]` with no repeated `.`, checked at user creation, plus a
  second, independent defensive check inside `recording_key()` itself (the
  one chokepoint every caller passes through) that raises `ValueError` on
  any component containing `/`, `\`, or `..`. `user_id` itself was always
  server-generated (`uuid.uuid4().hex`) and never attacker-influenceable.
  Both layers are unit-tested (`test_storage.py`,
  `test_auth_and_users.py::test_admin_create_user_rejects_unsafe_username`).
- **Signed object access / arbitrary file access**: **N/A — not
  introduced.** Recordings are never served via a presigned MinIO URL or any
  other client-facing storage reference; the app always streams bytes
  through its own authenticated route (`StreamingResponse` over
  `storage.open_stream()`), the same trust boundary the old `FileResponse`
  had.
- **Upload abuse**: **PASS, unchanged.** `MAX_UPLOAD_SIZE` enforcement,
  the per-user upload rate limit, and the temp-file-then-storage-upload flow
  are functionally the same as before; only the final destination changed.
- **Redis exposure**: **PASS by design.** `docker-compose.prod.yml`'s
  `redis` service uses `expose:`, never `ports:` — unreachable from outside
  the Compose network. Holds no durable data, so even a hypothetical
  internal-network compromise of Redis exposes nothing beyond rate-limit
  bucket contents (which key names, not content, of any sensitivity — see
  `rate_limit.py`'s key scheme, `scope:user_id`/`global-ip:ip`).
- **MinIO exposure**: **PASS by design.** Same `expose:`-only treatment;
  `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY` required and never defaulted to a
  known value in production (`config.py`'s fail-closed guard).
- **PostgreSQL exposure**: **PASS, unchanged** from the pre-existing
  `db` service (`expose:` only, no host port).
- **Secret leakage**: **PASS.** Re-checked every new `log.*` call site
  added this pass (`storage/*.py`, `redis_client.py`, `rate_limit.py`,
  `live_sessions.py`, `server.py`) — none log a key name's value, a
  connection string, or recording content; only variable names and storage
  keys (which are opaque IDs, not secrets).
- **SSRF**: **PASS, not introduced.** `MINIO_ENDPOINT`/`REDIS_URL` are
  operator-supplied config, never derived from user input at request time —
  no new code path constructs an outbound URL/connection from a client-
  supplied value.
- **Rate-limit bypass**: **PASS, semantics preserved and verified.** The
  Redis-backed sliding window was checked against the exact same
  "rejected hits don't count," "independent per-key windows," and
  "window rolls forward correctly" behaviors the old in-memory version had
  — via real Lua execution against fakeredis, not by inspection alone
  (`test_rate_limit.py`).
- **Proxy header spoofing**: **PASS, unrelated/unchanged.** The
  X-Forwarded-For fix from the prior audit pass (P1-A,
  `DEPLOYMENT_READINESS_AUDIT.md`) is untouched by this work; nginx's
  `resolver`/`$backend` addition (F7) only changes how the upstream
  hostname resolves, not header handling.
- **CORS/CSRF/security headers/TLS/container privilege**: **PASS,
  unchanged** — none of this pass's changes touch `_DevOnlyCORSMiddleware`,
  `frontend/nginx.conf`'s security headers, TLS config, or the Dockerfile's
  non-root `USER app`.
- **Exposed ports**: **PASS.** New services (`redis`, `minio`) follow the
  existing `db`/`web` pattern — `expose:` only in `docker-compose.prod.yml`,
  confirmed by reading the file, not assumed.

---

## G. Multi-replica validation

**UNVERIFIED — could not be run in this tool environment (no Docker).**
What *was* verified as a substitute, and what still needs to happen on your
VM:

- **Verified here:** every component that doesn't require multiple actual
  OS processes/containers talking over a real Docker network — the storage
  abstraction (real filesystem + mocked MinIO client), the Redis-backed
  rate limiter (real Lua execution via fakeredis), migration
  verification logic, graceful-shutdown bookkeeping, and the full existing
  application test suite (129 tests) against a real local Postgres.
- **Needs your VM, exact procedure:**
  1. `docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build --scale web=3`
  2. Confirm all 3 `web` replicas are healthy: `docker compose -f docker-compose.prod.yml ps`
  3. Log in repeatedly (curl in a loop, or just refresh a few times) and confirm you never get a spurious 401 — proves `SERVER_BOOT_ID` is genuinely shared.
  4. Record something, then repeatedly `GET /api/recordings/{id}/audio` — confirm it succeeds regardless of load-balancer routing (impossible to fully control which replica answers without inspecting nginx's own load-balancing directly, but repeated requests across a short window should exercise more than one replica if F7's fix is working).
  5. Hit a rate-limited route (e.g. `/api/recordings` — 120/60s) enough times from one session to trip the limit, and confirm the 429 arrives at a consistent total count regardless of which replica answers each request — proves Redis-backed rate limiting is genuinely shared (the specific failure mode being tested for: a limit that resets or triples because each replica had its own counter).
  6. `docker compose -f docker-compose.prod.yml stop web-2` (or whichever replica name Compose assigns) mid-use — confirm the app keeps working for other users, and no data is lost.

---

## H. Failure testing

**UNVERIFIED — needs Docker.** What the failure-mode design predicts (see
`SCALABILITY_DESIGN.md` §8), to be confirmed on your VM:

- **Redis killed**: rate-limited routes should return 503 (not 429, not
  silently pass through) — `rate_limit.RateLimiterUnavailable` → each call
  site's fail-closed handling. Recovers automatically once Redis returns
  (no restart needed, since `redis_client.get_client()` is a lazy
  reconnecting client).
- **MinIO killed**: new recordings should fail to persist (logged, not
  crashing the session — matches the existing "log and continue" pattern
  already used for the DB-registration step); existing recording
  downloads should return 503 (not 404, and not an unhandled 500) —
  `get_audio`/`get_transcript` (`routes_api.py`) distinguish
  `StorageNotFound` (404 - the object genuinely doesn't exist) from any
  other storage exception (503 - the backend itself couldn't be reached,
  logged server-side, "try again shortly" to the client). This gap was
  found during this pass's own review and fixed the same session (unit
  tests: `test_recordings.py::test_{transcript,audio}_returns_503_not_500_when_storage_backend_errors`)
  — the actual behavior against a real killed MinIO container is still
  UNVERIFIED (needs Docker), but the code path and its test are real.
- **Postgres killed**: `/healthz` already correctly 503s
  (pre-existing, unchanged, re-confirmed by reading `server.py`).
- **`web` replica killed**: other replicas keep serving; no durable state
  was ever local to the killed replica (once F1/F2/F3 are fixed) — WS
  sessions on that replica are lost, matching the accepted, documented WS
  lifecycle model.
- **`web` replica restarted (SIGTERM)**: graceful-drain behavior
  (`live_sessions.py`, `server.py`'s shutdown hook) is implemented and
  bookkeeping-tested, but **whether a real active live-recording WebSocket
  actually survives to persist its recording during a real SIGTERM is
  UNVERIFIED** — this needs a live browser session (or a WS test client)
  against a running container, sent a real SIGTERM, with the resulting
  recording checked for completeness. Exact manual test: start a live
  recording, `docker compose -f docker-compose.prod.yml kill -s SIGTERM web`
  (or `restart`), confirm the recording appears intact afterward.

---

## I. Remaining limitations — explicit, by category

- **API horizontal scalability**: implemented and code/unit-level verified;
  multi-replica runtime behavior UNVERIFIED (§G).
- **Database HA**: not attempted — `db` is a single Postgres instance;
  its loss is a full outage until restored from backup. Out of this pass's
  scope (task brief's "use PostgreSQL as the shared relational database,"
  not "make it HA").
- **Redis HA**: not attempted, and lower-priority by design — Redis here
  holds only reconstructible rate-limit counters; an outage degrades to
  fail-closed 503s on rate-limited routes, not data loss, and self-heals
  the moment Redis returns.
- **MinIO HA**: not attempted — a single MinIO instance/single disk is
  explicitly not redundant storage (`DEPLOYMENT.md`'s "If you scale beyond
  one VM" section says this plainly, per the task brief's instruction not
  to overclaim here).
- **VM HA**: not attempted — this is still a single-VM deployment; the VM
  is a single point of failure for `db`/`redis`/`minio` regardless of `web`
  replica count.
- **Real-device mobile testing, load/soak testing**: unchanged,
  pre-existing limitations, out of this pass's scope.

---

## J. Exact deployment instructions

```bash
# 1. Fill in the new required vars alongside the existing ones
cp .env.production.example .env.production
#   fill in: POSTGRES_PASSWORD, SONIOX_API_KEY, JWT_SECRET, ADMIN_PASSWORD,
#            SERVER_BOOT_ID (now REQUIRED, not optional - pin it),
#            REDIS_URL (default redis://redis:6379/0 works out of the box),
#            STORAGE_BACKEND=minio, MINIO_ACCESS_KEY, MINIO_SECRET_KEY
#            (MINIO_ENDPOINT=minio:9000 default works out of the box),
#            DOMAIN, CERTBOT_EMAIL

# 2. Hand-edit the real domain into frontend/nginx.conf (unchanged step)

# 3. One-time TLS bootstrap (unchanged step, still itself unverified per
#    DEPLOYMENT_READINESS_AUDIT.md's P1-B - unrelated to this pass)
./scripts/init-letsencrypt.sh

# 4. Bring up a single replica first and confirm it works before scaling
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps   # migrate should show "Exited (0)"; the rest healthy

# 5. Run this document's §G multi-replica validation
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --scale web=3

# 6. Run this document's §H failure tests

# 7. Full test suite on the exact deployed commit
python -m flake8 voice_transcriber scripts --max-line-length=120
python -m pytest -q
npm --prefix frontend run build
npm --prefix frontend test -- --run

# 8. Tag the release
git tag deploy-$(date +%Y%m%d) && git push --tags   # only if you want this pushed
```

---

## Final readiness rating: READY FOR STAGING

Justification: the code is complete, internally consistent, and tested as
thoroughly as this environment allows (131 backend tests + 212 frontend
tests green across multiple repeated runs — one of those repeats caught a
real, now-fixed Redis Lua script bug, not just a rubber-stamped single
pass; real Postgres, real Lua-executing fakeredis, no known dependency
vulnerabilities). It is not rated PRODUCTION READY because the single most
important claim of this entire effort — "multiple `web` replicas actually
work together correctly" — has not been observed running, only reasoned
through from code and documented Docker/nginx behavior. That gap is exactly
what §G's procedure closes. Run it on your VM and this becomes a fair
PRODUCTION READY claim.
