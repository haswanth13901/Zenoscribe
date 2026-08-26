# Zenoscribe — Horizontal Scalability Design (Phase 2)

Builds directly on `SCALABILITY_AUDIT.md`'s findings (F1-F11). No code
changes in this document either — this is the design to implement in
Phase 3, written against the actual current code (file/line references
match the audit), not a generic template.

---

## 1. Scope decisions (and what's deliberately excluded)

- **No job queue / worker fleet.** F6 in the audit already showed
  batch-upload capacity scales correctly per-replica via its own bounded
  `ThreadPoolExecutor`. Live transcription/translation is an inherently
  synchronous bidirectional stream to Soniox — there's nothing to "queue,"
  the WS connection *is* the unit of work and already scales by adding
  replicas (F8). Adding Celery/RQ/etc. here would be exactly the
  unnecessary-microservice the task brief warns against. **Decision: skip
  §9 of the task brief's worker-queue architecture entirely** — nothing in
  this codebase benefits from it. If this changes later (e.g. a genuinely
  slow batch job appears), revisit then.
- **No Kubernetes.** Docker Compose + `--scale` + an nginx fix (F7) gets to
  N replicas without it, matching the task brief's explicit preference.
- **MinIO for object storage, Redis for rate limiting/shared ephemeral
  state, Postgres unchanged as the relational source of truth.** Exactly
  the three components named in the task brief, no more.
- **Migrations become an explicit deploy-time step, not a per-replica
  startup action.**

---

## 2. Storage: `StorageService` abstraction

### Interface (`voice_transcriber/storage/base.py`)

```python
class StorageService(Protocol):
    def upload(self, key: str, local_path: Path, content_type: str) -> None: ...
    def download_to(self, key: str, local_path: Path) -> None: ...
    def open_stream(self, key: str) -> BinaryIO: ...   # for FileResponse-style streaming without a full local copy
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
```

Kept synchronous (matching `db.py`'s existing pattern of plain sync calls
wrapped in `asyncio.to_thread` at call sites) — consistent with the rest of
the codebase rather than introducing a second async convention.

### Key scheme

```
users/{user_id}/recordings/{recording_id}.wav
users/{user_id}/recordings/{recording_id}.txt
```

`recording_id` is already the `session` string generated in
`transcribe.py:139`/`translate.py:146`/`routes_api.py:414` (timestamp +
username + random suffix) — reused as-is, just relocated into this key
shape instead of a bare local filename. Scoping by `user_id` in the key
namespace is defense-in-depth on top of the existing DB-level ownership
check (`_authorize_recording`, `routes_api.py:332`) — never the actual
authorization mechanism, same relationship `nginx`'s static-file serving has
to the app's own auth today (belt, not buckle).

### Backends

- `LocalStorageService` — wraps today's `config.RECORDINGS` behavior
  exactly (for `STORAGE_BACKEND=local`, dev/test default, matching the task
  brief's §25 backward-compat request). This is close to a no-op refactor:
  extract the existing `Path` read/write/unlink call sites in
  `transcribe.py`, `translate.py`, `routes_api.py` behind this interface.
- `MinioStorageService` — production backend
  (`STORAGE_BACKEND=minio`), using the `minio` Python SDK. Bucket name from
  `MINIO_BUCKET`; endpoint/keys/TLS from `MINIO_ENDPOINT`/
  `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`/`MINIO_SECURE`.
- Selected once at import time in a new `voice_transcriber/storage/__init__.py`
  (`get_storage()` factory reading `config.STORAGE_BACKEND`), same pattern
  `db.py` uses for its pool singleton.

### Call-site changes

| Current | Becomes |
|---|---|
| `wave.open(str(config.RECORDINGS / f"{session}.wav"), "wb")` (`transcribe.py:142`, `translate.py:149`) | **Unchanged.** Still write to a local temp path during the live session (F1's reasoning: the WS connection is pinned to one replica for its life anyway, and `wave` needs a real seekable file handle for incremental writes). Use `tempfile.mkdtemp()`/a scratch dir instead of the shared `recordings/` name, since the file is no longer meant to persist there. |
| `db.add_recording(...)` in the `finally` block (`transcribe.py:421-431`, `translate.py:510-522`) | Preceded by `storage.upload(key, local_wav_path, "audio/wav")` and `storage.upload(key, local_txt_path, "text/plain")`; local temp files removed after a successful upload. `add_recording`'s `wav_file`/`txt_file` params now receive the storage key, not a bare filename — no schema change needed since those columns already just hold a string identifier (confirmed: `db.py`'s schema treats them as opaque strings, never parses them). |
| `shutil.move(tmp_path, audio_path)` (`routes_api.py:419`) | `storage.upload(key, Path(tmp_path), content_type)`, then `os.unlink(tmp_path)`. |
| `FileResponse(config.RECORDINGS / row["wav_file"])` (`routes_api.py:369`) | `StreamingResponse(storage.open_stream(row["wav_file"]), media_type=...)` — keeps the existing `_authorize_recording()` check as the gate (unchanged), only the byte-source changes. |
| `path.read_text()` for transcripts (`routes_api.py:349-352`) | `storage.download_to(key, tmp) ; tmp.read_text()`, or a small `get_text(key)` convenience on the interface — transcripts are small, no need for streaming here. |
| `(config.RECORDINGS / name).unlink()` (routes_api.py delete paths, `db.py`'s callers) | `storage.delete(key)`. |
| `scripts/reconcile_recordings.py` | Gains a `--backend minio` mode using `storage.exists()`/a `list_objects` call instead of `Path.glob()`, run as a periodic operational check the same way the local-disk version is documented today (`DEPLOYMENT.md` §2). |

### Failure/authorization behavior to preserve exactly

- 404 (never 403) on missing file or wrong owner — unchanged, enforced
  before any storage call, not after.
- No raw filesystem/bucket path or presigned URL is ever handed to the
  client directly for recordings — the app streams bytes through itself
  (`StreamingResponse`), same trust boundary as today's `FileResponse`. (A
  presigned-URL download is a reasonable future optimization but changes
  the security model — MinIO would need to be reachable from the client's
  browser, which the task brief's "never expose MinIO... without protection"
  constraint makes non-trivial. Deferred; not needed to hit the scaling
  goal.)

---

## 3. Redis: rate-limiting abstraction

### Interface (`voice_transcriber/redis_client.py`)

Thin wrapper, not a scattering of raw `redis.Redis()` calls:

```python
def get_client() -> redis.Redis: ...   # singleton, from REDIS_URL
```

### Rate limiter redesign (`rate_limit.py`)

Preserve the exact semantics documented in the audit §6:
- Sliding window, not fixed window (avoids the classic edge-burst-at-boundary
  bug a naive fixed-window `INCR`+`EXPIRE` would introduce — a real behavior
  change the task brief says not to make).
- Rejected hits don't consume quota.

Implementation: a Lua script executed via `EVAL` (atomic, avoids
check-then-act races across replicas hitting Redis concurrently) that
mirrors `hit()`'s current deque logic using a Redis sorted set per key
(`ZADD` with the timestamp as score, `ZREMRANGEBYSCORE` to expire, `ZCARD`
to check the limit) — a direct, well-established translation of "trailing
window of timestamps" from a Python `deque` to a Redis `ZSET`, keeping
`hit(key, limit, window_sec) -> bool`'s exact signature and behavior so
every call site (`per_user()`, the two `ws-connect` call sites, and
`GlobalRateLimitMiddleware`) needs zero changes beyond the import.
`reset_all()` (test-only) becomes `FLUSHDB` against a dedicated test Redis
DB index, matching how `conftest.py` already isolates Postgres per test via
schemas (per memory) — same isolation philosophy, different mechanism.

`GlobalRateLimitMiddleware`'s raw-ASGI structure (`rate_limit.py:85-131`) is
unchanged — it's already backend-agnostic, calling `hit()` the same way HTTP
and WS paths do today.

### What stays out of Redis

Per the task brief's explicit instruction: `failed_logins` (F11, already
Postgres) stays there — it's already correct and durable, and a login
lockout that resets on a Redis restart would be a real regression. No
recording/user/session data goes into Redis at all — it is exclusively
rate-limit counters plus the WS connect-throttle keys, both inherently
ephemeral and reconstructible (worst case after a Redis restart: a brief
window of unenforced rate limits, not data loss).

---

## 4. Migrations: deploy-time step

- Remove the unconditional `db.init()` call from `server.py`'s startup hook.
- `db.init()` itself (`db.py:50-54`) stays as-is (it's just a thin wrapper
  around `alembic.command.upgrade`) — it becomes something invoked
  explicitly, not automatically.
- New mechanism: a one-shot Compose service (`migrate`, same `web` image,
  overridden command: `python -c "from voice_transcriber import db; db.init()"`)
  that runs to completion *before* `web` replicas start, via `depends_on`
  with `condition: service_completed_successfully`. This keeps the
  self-hosted/Compose-only constraint (no separate CI-runs-migrations step
  required, though that remains a valid alternative for teams with a CI/CD
  pipeline that can reach the production DB).
- `server.py`'s startup hook instead does a **read-only** check: query
  `alembic_version` and compare against the code's expected head revision;
  refuse to serve traffic (fail `/healthz`, or hard-exit — TBD in Phase 3
  based on which gives a clearer operator signal) if they don't match. This
  catches "someone forgot to run the migrate step" as a loud failure instead
  of the silent wrong-schema behavior that would otherwise result.
- `auth.ensure_seed_admin()` (`server.py:92-104`) is unrelated to schema
  migration (it's a data seed, not DDL) and can safely stay as an
  idempotent per-replica startup check — it already only acts when
  `db.count_admins() == 0`, so N replicas racing it concurrently is
  already safe (worst case, a harmless duplicate `SELECT COUNT`).

---

## 5. Reverse proxy / load balancing (F7 fix)

`frontend/nginx.conf`'s four `proxy_pass http://web:8000` locations change
to use Docker's embedded DNS resolver plus a variable, forcing re-resolution
instead of a one-time cached lookup:

```nginx
resolver 127.0.0.11 valid=10s;
set $backend "web";
proxy_pass http://$backend:8000;
```

(one `resolver`/`set` pair per server block, reused by all four locations in
that block). This is the standard, well-documented fix for load-balancing
across a Compose `--scale`d service name — Docker Compose's embedded DNS
already round-robins A records for a scaled service, nginx just needs to
actually ask it repeatedly instead of caching the first answer.
**UNVERIFIED claim until tested against a real `docker compose up --scale
web=3`** on your VM (Phase 4) — no Docker available here to confirm nginx's
resulting balancing behavior directly, only its documented resolver
semantics.

WebSocket timeouts (`proxy_read_timeout 0`, `frontend/nginx.conf:109-110`)
and the X-Forwarded-For fix (`$remote_addr`, already correct per
`DEPLOYMENT_READINESS_AUDIT.md`'s P1-A) are unaffected and stay as-is.

Scaling command: `docker compose --env-file .env.production -f
docker-compose.prod.yml up -d --scale web=3` — documented precisely in
Phase 3's updated `DEPLOYMENT.md`.

---

## 6. Graceful shutdown

New `server.py` shutdown sequence, replacing the current DB-pool-only
handler:

1. A module-level `shutting_down = False` flag (process-local is correct
   here — this is per-instance drain state, not shared state) flipped by a
   `signal.signal(signal.SIGTERM, ...)` handler (or FastAPI's shutdown
   event, whichever gives access to signal timing more directly — decided
   in Phase 3).
2. `/healthz` immediately starts returning 503 once `shutting_down` is
   true, so nginx/an external LB stops routing new HTTP requests and new WS
   connection attempts to this replica (nginx itself doesn't consult
   container health per-request today — this relies on the orchestration
   layer polling `/healthz`, consistent with the existing documented
   limitation in `DEPLOYMENT_READINESS_AUDIT.md`'s P2 notes).
3. Active WS sessions are **not** killed immediately — `transcribe.py`/
   `translate.py`'s existing `finally` blocks already persist correctly on
   any clean close; the shutdown handler instead sends a `{"type":
   "server_restarting"}` notice (new, small addition) and starts a bounded
   grace timer (e.g. 30s, configurable) before forcing closure of any
   session still open, giving in-flight turns time to flush.
4. Only after the grace period (or all sessions closing on their own,
   whichever first) does the process allow uvicorn's normal shutdown to
   proceed and `db.close_pool()` to run.

This directly addresses the audit's §5 finding (data loss risk during
rolling restarts) without touching the turn-detection/session logic itself.

---

## 7. Configuration additions

New env vars (validated at startup, fail-closed in production, matching
`config.py`'s existing pattern for `DATABASE_URL`/`SONIOX_API_KEY`):

```
STORAGE_BACKEND=local|minio      # required in production: must be "minio"
MINIO_ENDPOINT
MINIO_ACCESS_KEY
MINIO_SECRET_KEY
MINIO_BUCKET
MINIO_SECURE=true|false

REDIS_URL                        # required in production

SERVER_BOOT_ID                   # promoted from "strongly recommended" to
                                  # a hard production requirement (F3) -
                                  # config.py gains the same fail-fast guard
                                  # pattern as DATABASE_URL/SONIOX_API_KEY

DB_POOL_MAX_SIZE                 # replaces the hardcoded 10 in db.py:33,
                                  # documented sizing table added to
                                  # DEPLOYMENT.md (F5): total budget =
                                  # Postgres max_connections / N replicas,
                                  # minus headroom for the migrate job/admin
                                  # connections
```

`STORAGE_BACKEND=local` remains the dev/test default (docker-compose.yml
unchanged in spirit) so nothing in local dev requires standing up MinIO —
matching the task brief's §25 backward-compatibility request. Production
`docker-compose.prod.yml` sets `STORAGE_BACKEND=minio`/`REDIS_URL` and gains
`minio` and `redis` services alongside the existing four.

---

## 8. Failure handling matrix

| Dependency down | Behavior |
|---|---|
| Postgres unreachable | `/healthz` already 503s (`server.py:186-198`, unchanged) — external monitoring (already documented as an operational requirement) alerts. New: the read-only migration-version check at startup also fails closed if Postgres is unreachable at boot. |
| Redis unreachable | Rate limiting fails **closed or open**? Decision for Phase 3: closed (reject requests) is safer but turns a Redis blip into a full outage; open (allow through) preserves availability but briefly loses the abuse protection. Given the task brief's "never weaken security for scalability," default to a short-timeout-then-fail-closed with a clear 503, not silent open — final call documented in Phase 3 alongside the actual timeout value chosen. |
| MinIO unreachable | New recordings can't be persisted — live sessions should still complete and notify the user their recording couldn't be saved (not silently drop it, not crash the whole session), matching the existing "log and continue" resilience pattern already used for the DB-registration step (`transcribe.py:432-433` catches and logs rather than raising). Existing recordings become undownloadable until MinIO returns — a 503-equivalent on `/api/recordings/{id}/audio`, not a 404 (which would incorrectly imply the recording doesn't exist/isn't the user's). |
| One `web` replica killed | No durable state lost (F1-F5 fixes make replicas disposable) — in-flight WS sessions on that replica end (acceptable per the task brief's WS model), other replicas unaffected. |

---

## 9. Backups

- **Postgres**: unchanged from `DEPLOYMENT.md` §2's existing `pg_dump`
  approach — still correct, not affected by the horizontal-scaling work.
- **MinIO**: replaces the `recordings` named-volume `tar` backup
  (`DEPLOYMENT.md` §2) with `mc mirror` (MinIO's own client) to an off-host
  destination, run on the same schedule as the Postgres dump. Consistency
  requirement carries over unchanged: restore both from backups taken close
  together in time, then run the MinIO-aware `reconcile_recordings.py`
  (§2 above) to check for drift — same procedure as today, different
  backend.

---

## 10. Testing plan (Phase 3 will implement these)

- Unit: `StorageService` (both backends) — upload/download/delete/missing/
  a permission-denied case for MinIO's own IAM if configured; Redis rate
  limiter — concurrent-client sliding window, expiry, limit enforcement,
  rejected-hits-don't-count.
- Integration: extend `conftest.py`'s existing fixture pattern (already
  spins up an isolated Postgres schema per test, per memory) with an
  isolated Redis DB index and a MinIO test bucket/prefix per test run.
- Multi-replica: a new test harness that starts 2-3 `uvicorn` processes
  against the same Postgres/Redis/MinIO (no Docker required for this
  specific test tier — plain subprocesses on different ports, nginx
  substituted with a trivial round-robin test proxy or direct per-replica
  requests asserting shared state) proving login/recordings/rate-limits
  are consistent across them. This tier *can* run in this environment
  without Docker; the real nginx+Docker-Compose-scale end-to-end proof
  (F7) cannot, and stays marked UNVERIFIED until run on your VM.
- Failure tests: kill Redis/MinIO mid-suite (testcontainers-style or a
  fake that can be toggled) and assert the failure-matrix behavior in §8,
  not just that an exception is caught.

---

## 11. Sequencing for Phase 3

To keep each step reviewable and testable independently (task brief's "run
tests after each major change" instruction):

1. `StorageService` + `LocalStorageService`, refactor all current call sites
   to use it with `STORAGE_BACKEND=local` — no behavior change, full test
   suite must stay green. This alone de-risks everything after it.
2. `MinioStorageService`, config/env additions, docs.
3. Redis rate limiter, behind the same `hit()`/`per_user()` interface — no
   call-site changes needed once this lands.
4. Migration-as-deploy-step + read-only startup check.
5. nginx resolver fix + Compose scaling docs.
6. Graceful shutdown.
7. Docs (`DEPLOYMENT.md`, `README.md`, new architecture doc), backup script
   updates, CI additions (Redis/MinIO services, multi-replica test job).
8. Security re-audit of every changed component (task brief §19/§6 of
   process) — done last, against the actual final diff, not speculatively
   now.
