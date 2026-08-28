# Zenoscribe — Horizontal Scalability Audit (Phase 1: Discovery)

*Audited against commit `bf64f72` (2026-08-25), working tree otherwise clean
except an unrelated `.claude/settings.json` change. No application code
changed as part of this document — discovery only, per the requested
process.*

**Environment constraint, stated up front:** this audit was produced without
Docker, Redis, or MinIO available in the local tool environment (Windows,
Git Bash — `docker`, `docker compose`, `redis-server` all absent). Every
finding below is traced from reading the actual source, not assumed or
guessed. Anything that requires actually running the stack (a live 3-replica
test, a real `docker compose up --scale`, nginx behavior under Docker's
embedded DNS) is called out explicitly as **UNVERIFIED — needs your VM**, per
the ground rules. The good news: this codebase already has two internal
documents (`E2E_Review.md` §"Open items"/1, `DEPLOYMENT_READINESS_AUDIT.md`
§"If you scale beyond one container") that correctly anticipated most of the
real blockers, in general terms, before this audit started. This document
turns those into a concrete, file-and-line map plus a target design.

---

## 1. What Zenoscribe actually is (for grounding the rest of this doc)

FastAPI + Postgres backend, hybrid frontend (vanilla-JS login page, React+RTK
SPA for everything post-login), custom JWT+bcrypt auth (no cookies, no
server-side session store). Five user-facing features: live transcription
(`/ws`), live two-way translation with TTS playback (`/ws/translate`), batch
upload transcription/translation (`/api/transcribe`,
`/api/transcribe/translate`), recording history/download
(`/api/recordings/*`), and an admin console. One relational store (Postgres,
migrated from SQLite in the prior session — see memory). Recordings are WAV
audio + a plain-text transcript per session, written to a local
`voice_transcriber/recordings/` directory and referenced from Postgres by
bare filename.

Current shipped topology (`docker-compose.prod.yml`, `Dockerfile`,
`frontend/Dockerfile`, `frontend/nginx.conf`) — **already three separate
images**, which is a better starting point than a single monolith image:

```
                         Internet
                            |
                      nginx (TLS, :80/:443)
                    (frontend/Dockerfile + nginx.conf)
                            |
                 +----------+-----------+
                 |                      |
         static SPA/login       proxy_pass http://web:8000
         (baked into image,     (single, hardcoded hostname -
          fully stateless)       see Finding F7 below)
                                        |
                                    web (FastAPI, --workers 1)
                                        |
                              +---------+---------+
                              |                   |
                        Postgres (db)     local named volume
                        (shared, real)    `recordings` (NOT shared -
                                           see Finding F1)
```

`web` and `db` are the two components that currently block horizontal
scaling. `nginx` (static assets + TLS) is already stateless and would scale
fine standalone. This matches `DEPLOYMENT.md` §4's own stated limitation.

---

## 2. Process-local / non-scalable state — full inventory

Every module-level mutable global in `voice_transcriber/` was enumerated
(via a targeted grep for `_name = {…}` / `ConnectionPool` / `threading.*`
patterns across the package) and classified below. Nothing was assumed safe
without tracing its read/write sites.

| # | State | Location | Classification | Why |
|---|---|---|---|---|
| F1 | Recordings (WAV + transcript files) | `config.RECORDINGS` = `voice_transcriber/recordings/`, written in `transcribe.py`, `translate.py`, `routes_api.py`; read in `routes_api.py` (`get_audio`/`get_transcript`), deleted in `routes_api.py`/`db.py` | **MUST MOVE** | Local Docker named volume, one per container. A second `web` replica cannot see the first's files — a user recording on replica A and later downloading from replica B (very likely under any real load balancer) gets a 404 "Audio missing" even though the DB row and the file both genuinely exist, just on the wrong host. See §3 for the detailed design — this is the highest-priority fix, exactly as the task brief anticipated. |
| F2 | `rate_limit._buckets` (dict of deques) + `rate_limit._lock` | `voice_transcriber/rate_limit.py:35-36` | **MUST MOVE** | Explicitly documented in the module's own docstring as single-process only. Backs three things: (a) `per_user()` — the FastAPI dependency used by every write-ish HTTP route (admin writes, `/api/recordings*`, uploads); (b) `hit()` direct calls — WS connection throttling (`ws-connect:{user_id}`) in both `transcribe.py:56` and `translate.py:79`; (c) `GlobalRateLimitMiddleware` — the per-IP net over every HTTP+WS request. With N replicas behind a load balancer, a user's effective quota becomes up to N× the configured limit (round-robin dependent, not even a hard multiplier) — not an auth bypass, but a real precision loss the task brief specifically calls out as unacceptable ("10+10+10 ≠ 30"). |
| F3 | `auth.SERVER_BOOT_ID` | `voice_transcriber/auth.py:60` | **SAFE, CONDITIONALLY** — needs an operational guarantee, not a code fix | Stamped into every JWT's `boot` claim (`auth.py:82`) and checked on every request (`auth.py:103`). If left unset, each process generates its own random value at import time — with N replicas that means a token issued by replica A is silently rejected by replica B (`user_from_token` returns `None` → generic 401), i.e. sessions would randomly break depending on load-balancer routing. **This is already a documented requirement to set explicitly** (`DEPLOYMENT.md` §1's "Strongly recommended" row) — but today nothing enforces or verifies that every replica in a fleet actually received the *same* value, and there's still no way to revoke one specific session or do a live, zero-downtime boot-id rotation across replicas. Classify as safe for the multi-replica case *only if* `SERVER_BOOT_ID` is a required, fail-closed production config value (currently just "strongly recommended") shared via the same `.env.production`/secret store every replica reads. Recommend hardening this from "strongly recommended" to a hard startup guard (§4 below), and optionally backing it with Redis later for real per-session revocation — but that is a genuine feature gap (no logout endpoint), not a scaling blocker, so it's scoped as P2, not P0/P1. |
| F4 | Alembic migrations at startup | `db.init()` called unconditionally from `server.py`'s `@app.on_event("startup")` (`server.py:91`), no advisory lock in `db.init()` (`db.py:50-54`) | **MUST MOVE (to an explicit deploy step)** | Fine today only because `--workers 1` and a single container make concurrent execution impossible by construction (correctly noted as a non-issue in `DEPLOYMENT_READINESS_AUDIT.md`). The moment a second `web` replica starts — whether by design (scaling up) or by accident (a rolling deploy briefly running old+new together) — two processes will call `alembic upgrade head` against the same database with no coordination. Alembic does not itself take a Postgres advisory lock; two concurrent `upgrade head` calls racing on `alembic_version` can produce a corrupted migration state or a mid-DDL failure, not just a benign no-op. This graduates from "accepted limitation" to a **must-fix** the instant a second replica exists. |
| F5 | `psycopg_pool.ConnectionPool` (`min_size=1, max_size=10`) | `voice_transcriber/db.py:26-39`, module-level singleton `_pool` | **SAFE structurally, needs tuning as replicas scale** | Each replica gets its own independent pool — this is correct, expected behavior (no shared mutable state issue). The problem is purely arithmetic: hardcoded `max_size=10` per process × N replicas can exceed Postgres's `max_connections` (default 100) well before N=10, especially once a worker/migration-runner process is added. Needs to become configurable (env var) with documented sizing guidance (§10 below), not a code correctness fix. |
| F6 | `_UPLOAD_EXECUTOR` (`ThreadPoolExecutor(max_workers=3)`) | `voice_transcriber/routes_api.py:51-53` | **SAFE FOR MULTI-REPLICA** | Purely a per-process concurrency cap so batch-upload transcription can't starve the shared default executor (which also serves `db.touch_seen` and live-session audio writes). Each replica having its own budget is the desired behavior — total upload capacity scales linearly with replica count, which is exactly what horizontal scaling should give you here. No change needed. |
| F7 | `frontend/nginx.conf`'s `proxy_pass http://web:8000;` (4 locations: `/ws`, `/ws/translate`, `/api/`, `/healthz`) | `frontend/nginx.conf:89-140` | **MUST FIX (config, not app code)** | nginx resolves a plain hostname in `proxy_pass` **once**, at worker-process startup, and caches the IP for that worker's lifetime — it does not re-resolve on every request. Docker Compose's embedded DNS returns multiple A records for a scaled service name (`docker compose up --scale web=3`), but plain `proxy_pass http://web:8000` will pin to whichever single IP nginx resolved first and never rebalance across the others, and will hard-fail if that specific container is later replaced (new IP, same name) until nginx is reloaded. **This means `docker compose up --scale web=3` today would not actually load-balance** even though nothing else looks wrong — a classic "looks scalable, isn't" trap the task brief explicitly warns about (§23/§27). Needs `resolver 127.0.0.11 valid=10s;` (Docker's embedded DNS) plus a variable-based `proxy_pass http://$upstream:8000` (forces per-request/per-cache-TTL re-resolution), or a static multi-entry `upstream {}` block if replica count is meant to be fixed at deploy time. Traced from nginx's documented resolver/proxy_pass caching behavior; **UNVERIFIED against a real multi-replica Compose run** — needs confirming on your VM once changed (no Docker available here). |
| F8 | In-connection WebSocket state (`state` dict, `turns` list, `write_queue`, `SpeakerLabeler`, watchdog/keepalive tasks) | `transcribe.py:62,115-124,148`; `translate.py` equivalents | **SAFE FOR MULTI-REPLICA** | All scoped to a single connection's closures/local tasks — nothing here is a cross-connection registry (no `active_sessions = {}` anywhere). This matches the task brief's explicit allowance: a WS connection may stay pinned to one replica for its life; what's *not* allowed is a second, unrelated request needing to land on that same replica, and nothing here creates that dependency. No change needed structurally — only the recordings-file destination (F1) and the shared rate limiter (F2) that these modules call into need to change. |
| F9 | `soniox_client.set_test_fake_mode()` module-level flag | `voice_transcriber/soniox_client.py:195` and its internal state | **SAFE (test/dev only, fails closed in prod)** | Only reachable via `/internal/test-hook/transcribe_mode`, which 404s unless `config.ALLOW_TEST_HOOKS=true` — and `config.py:107-108` already refuses to boot in production if that flag is set. No production scaling exposure; flagged here only for completeness per the instruction not to assume anything is safe without checking. |
| F10 | `languages.LANGUAGES` and similar static module constants | `voice_transcriber/languages.py` | **SAFE** | Read-only data, identical across processes, no mutation anywhere. |
| F11 | Login brute-force lockout (`failed_logins` table) | `db.py:80-104`, used from `routes_api.py:87-104` | **Already SAFE** | Explicitly Postgres-backed, not in-memory — this is the one rate-limit-shaped mechanism that already works correctly across replicas today, because it was built DB-backed from the start (per its own docstring in `rate_limit.py:20-22`, deliberately not touched by that module). No change needed. |

**Summary: three real blockers (F1 storage, F2 rate limiting, F4 migrations), one config-hardening item (F3), one tuning item (F5), one infra-config gap (F7). Everything else already generalizes to N replicas correctly.** This is a narrower blocker set than a from-scratch audit would typically find — the codebase's existing internal docs had already scoped this accurately.

---

## 3. Storage (F1) — detailed trace

Two write paths, one read path, all local-filesystem:

- **Live sessions** (`transcribe.py:142-146`, `translate.py:149-152`): a
  `wave.Wave_write` handle is opened directly against
  `config.RECORDINGS / f"{session}.wav"` at connection start, and PCM chunks
  are written incrementally throughout the session via an `asyncio.Queue` +
  single writer task (`audio_writer()`, both files) that calls
  `asyncio.to_thread(wf.writeframes, chunk)` — i.e., the file is built up
  live, chunk by chunk, for the whole duration of the call. This detail
  matters for the target design (§ below): the file **cannot** simply be
  "uploaded once at the end" from nowhere — it has to be assembled
  somewhere first, and today that "somewhere" is local disk.
- **Batch uploads** (`routes_api.py:391-454`, `_persist_upload_recording`):
  a temp file is transcribed, then `shutil.move()`d into
  `config.RECORDINGS` under a generated session name.
- **Reads** (`routes_api.py:342-371`, `get_transcript`/`get_audio`): both
  read straight off `config.RECORDINGS / row["wav_file"]` /
  `row["txt_file"]` and return a `FileResponse`/file contents. Ownership is
  correctly checked first via `_authorize_recording()` (`routes_api.py:332`)
  — this authorization logic is sound and must be preserved unchanged when
  the storage backend changes underneath it.
- **Deletes**: `routes_api.py:381-388` (user-initiated),
  `routes_api.py:240-251` (cascade on user deletion), `db.py:332-338`
  (returns filenames for the caller to unlink) — all local `Path.unlink()`.

**Why this doesn't need a bigger rewrite than it sounds like:** because a
live WS connection is already pinned to one replica for its lifetime (F8,
accepted by design), local buffering *during* the session is fine. The only
change needed is: assemble locally as today (or in a temp path), then — in
the `finally` block that already exists in both `transcribe.py` and
`translate.py` for exactly this purpose (closing the wav file, writing the
transcript, calling `db.add_recording`) — upload the finished object(s) to
MinIO instead of leaving them on the local volume, and store an
object-storage key in Postgres instead of (or alongside) the bare filename.
Reads/deletes then go through the same storage abstraction instead of
`Path`/`FileResponse` directly. `db.py`'s `wav_file`/`txt_file` columns
already hold what amounts to a storage key (a flat filename) — the schema
change needed is small (widen the semantic meaning of that column, or add an
explicit `storage_key` column via an expand/contract migration), not a
redesign.

`scripts/reconcile_recordings.py` (local disk vs. DB drift checker) will
need an equivalent for MinIO vs. DB, since the same class of drift (crash
mid-write, partial restore) is possible against object storage too.

---

## 4. Database & migrations (F4) — detailed trace

- `db.init()` (`db.py:50-54`) runs `alembic.command.upgrade(cfg, "head")`
  unconditionally on every call, and `server.py:91` calls it unconditionally
  on every app startup, with no lock, no "only if leader" check, no
  environment gate.
- Two migrations exist today (`b9a728687f5b_initial_schema.py`,
  `884a0b02cf74_add_recordings_source.py`), both with real, tested
  `downgrade()` bodies (per `DEPLOYMENT_READINESS_AUDIT.md`, re-confirmed
  structurally here).
- `CREATE EXTENSION citext` in the initial migration needs elevated Postgres
  privileges — already flagged in `DEPLOYMENT.md` §4 as a concern if the DB
  is ever moved to a managed service; irrelevant to this audit's
  self-hosted scope but worth carrying forward since it interacts with "who
  is allowed to run migrations" once that becomes a distinct, permissioned
  step.

**Target:** migrations become a one-time job run before new `web` replicas
start (`alembic upgrade head` as an explicit CI/deploy step, or a dedicated
one-shot container in Compose), and `db.init()`'s call site in `server.py`
either goes away entirely or is changed to a read-only "verify schema is at
the expected head, else refuse to serve" check — never a mutating call —
once more than one replica can start concurrently.

---

## 5. WebSockets — reconnect, shutdown, lifecycle

- **Auth**: both `/ws` (`auth.user_from_ws`, `auth.py:145-165`) and
  `/ws/translate` (inline in `translate.py:60-72`) bound the first-frame
  auth wait with a 10s timeout — already fixed per
  `DEPLOYMENT_READINESS_AUDIT.md`'s "Fixed" section, re-confirmed here by
  reading the code directly.
- **Per-connection resource limits**: `rate_limit.hit("ws-connect:{user_id}", 20, 300)`
  gates new connections per user in both modules, independent of the
  now-shared-store change needed for F2 — this logic itself is correct and
  just needs its storage backend swapped.
- **Reconnect handling**: not traced in this pass (frontend code, out of
  this backend-focused audit's file list so far) — flagged as a §8 item to
  verify in Phase 2/3: does `frontend/src/features/transcribe`'s
  `useRecorderConnection` hook (per memory) implement bounded
  exponential-backoff reconnect? Needs a direct read before design.
- **Graceful shutdown**: `server.py:107-109`'s `@app.on_event("shutdown")`
  only closes the DB pool. There is **no** handling today for "a SIGTERM
  arrives while N live sessions are mid-recording" — uvicorn's default
  shutdown behavior (stop accepting new connections, then forcibly cancel
  remaining tasks after its graceful-timeout window, which is not
  explicitly configured here so it uses uvicorn's default) would abruptly
  cancel `pump_audio`/`pump_results`/`audio_writer` tasks mid-write. The
  `finally` blocks in both `transcribe.py` and `translate.py` that persist
  the recording (`transcribe.py:386-438`, `translate.py:438-463`) may not
  get a chance to run to completion, or may race with the WAV file handle
  being torn down — a real, currently-undocumented **data-loss-on-rolling-restart**
  risk once restarts become routine (they will be, once there's more than
  one replica to roll). **MUST FIX** in Phase 3: an explicit SIGTERM
  handler that (a) flips `/healthz` to unready immediately so the LB stops
  routing new traffic and new WS connects, (b) sends a clean
  "server is restarting" close/notice to active sessions with a bounded
  grace period to let their `finally` blocks finish persisting, then
  (c) exits.

---

## 6. Rate limiting — current semantics to preserve

Documented here so the Redis migration doesn't silently change behavior
(the task brief requires preserving existing semantics):

- Per-user, per-scope sliding window via `hit()`/`per_user()`
  (`rate_limit.py:39-53,65-82`) — e.g. `admin-write` (60/60s),
  `recordings` (120/60s), `upload` (15/300s), `ws-connect` (20/300s).
- Global per-IP net, 600/60s, covering every HTTP+WS request
  (`GlobalRateLimitMiddleware`, `rate_limit.py:85-131`) — notably this is
  raw ASGI, not `BaseHTTPMiddleware`, specifically so it also covers
  WebSocket handshakes (`scope["type"] == "websocket"`, closes with code
  `4429`). Any Redis-backed replacement must preserve this WS-handshake
  coverage, not just HTTP.
- Login lockout is separate and already DB-backed (F11) — out of scope for
  the Redis migration, don't touch it.
- Rejected hits are not themselves counted (`hit()`'s docstring/behavior,
  `rate_limit.py:39-53`) — a client being throttled can't consume future
  quota by retrying. Must be preserved exactly (a naive Redis `INCR`-based
  rewrite could accidentally count rejected attempts too).

---

## 7. Container/deployment findings

- `web` has no `container_name:` in `docker-compose.prod.yml` — already
  compatible with `--scale`, structurally. Good, no change needed here.
- `web` already runs non-root (`Dockerfile:80,99,130`), already has no
  durable local data baked into the image itself (only the writable
  `recordings/` mountpoint, which F1 removes the need for), already reads
  all config from environment — this container is close to "disposable" as
  the task brief wants; the recordings volume is the only thing anchoring
  it to a specific host today.
- `--workers 1` is pinned with a clear, correct comment explaining exactly
  why (`Dockerfile:107-113`) — this reasoning stays valid; the fix is
  "run more single-worker containers," not "raise `--workers`," matching
  the task brief's explicit preference for Compose replicas over
  more-workers-per-process.
- No image registry, no git tags yet (already flagged as P2 in
  `DEPLOYMENT_READINESS_AUDIT.md`) — orthogonal to horizontal scaling itself
  but relevant to how replicas actually get updated in practice (§23/§10 of
  the task brief: safe rolling deploys want a fast, atomic image swap).
- CI (`ci.yml`) has no Redis or MinIO service containers, and no
  multi-replica test job — both need adding once those components exist
  (Phase 3 test work, not a Phase 1 finding beyond noting the gap).

---

## 8. Proposed target architecture (matches the task brief's diagram)

```
                                Internet
                                   |
                          nginx (TLS, :80/:443)
                    resolver 127.0.0.11 + variable
                    proxy_pass -> real load-balancing
                    across N `web` replicas  (fixes F7)
                                   |
              +--------------------+--------------------+
              |                    |                     |
           web #1               web #2               web #3
        (FastAPI, stateless: no local recordings,
         Redis-backed rate limits, migrations NOT
         run at startup)
              |                    |                     |
              +--------------------+--------------------+
                        |                        |
                     Postgres                  Redis
                (users, recordings        (rate-limit counters,
                 metadata, source          ws-connect throttles;
                 of truth)                 NOT durable business data)
                        |
                      MinIO
              (recording WAV + transcript objects,
               keyed users/{user_id}/recordings/{id}.wav etc.;
               Postgres row stores the storage key + metadata)
```

Migrations: a separate, explicit one-shot step (`alembic upgrade head`) run
before new `web` replicas start — not inside any replica's startup path.

Scaling mechanism for plain Docker Compose (no Swarm, per the task brief's
explicit preference): `docker compose -f docker-compose.prod.yml up -d
--scale web=3`, combined with the nginx `resolver`/variable-`proxy_pass` fix
(F7) so that scaling actually load-balances instead of silently pinning to
one replica. This needs to be demonstrated for real on your VM (Phase 4) —
it cannot be verified from this environment.

---

## 9. What Phase 1 deliberately does NOT cover yet

Per the requested process, no code was changed in this pass. Left for
Phase 2 (design) and Phase 3 (implementation):

- Exact `StorageService` interface and MinIO backend implementation.
- Exact Redis abstraction for rate limiting (key scheme, TTL/expiry
  semantics matching §6 above exactly).
- The migration-as-deploy-step mechanics (Compose one-shot service? CI job?
  both?).
- Graceful-shutdown implementation for live WS sessions.
- Frontend WebSocket reconnect behavior (not yet read in this pass).
- Monitoring/observability, backups, load testing, and the full security
  re-audit (task brief §18/§17/§22/§19) — all depend on the above existing
  first.

## 10. Environment limitations affecting later phases (stated now, not as a surprise later)

- **No Docker in this tool environment.** Every Compose/nginx/multi-replica
  claim in this document is derived from reading configuration and code,
  cross-checked against documented nginx/Docker DNS behavior — not from
  running it. `DEPLOYMENT_READINESS_AUDIT.md` already flagged the same
  constraint for the nginx/certbot migration (P1-B) — this audit inherits
  that same gap for anything touching MinIO/Redis/multi-replica Compose.
  Anything in Phase 3-5 that needs `docker compose up` to prove will be
  explicitly marked **UNVERIFIED** rather than asserted as working.
- **No Redis or MinIO available locally either** — the Redis
  abstraction and MinIO `StorageService` can and will be unit-tested against
  real local instances if you can provide connection details, or against
  `fakeredis`/a MinIO-compatible test double as a fallback; either way this
  will be stated plainly in the Phase 3/4 report, not glossed over.
