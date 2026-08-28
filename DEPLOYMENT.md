# Zenoscribe — Deployment Guide

For the deployment team. Target: a single Ubuntu VM (or more - see
"Scaling" below), Docker Compose, nginx in front for TLS (certbot-managed
Let's Encrypt certificate). Replaces `Req._deployment.txt`, which predated
the Compose setup — this is the one current doc, don't split back into two.

**Seven services, five separately-built/pulled images** (`docker-compose.prod.yml`):

| Service | Image | Role |
|---|---|---|
| `db` | stock `postgres:16-alpine`, no custom Dockerfile | Postgres - relational source of truth |
| `redis` | stock `redis:7-alpine`, no custom Dockerfile | Shared rate-limit counters only, no durable data - see `voice_transcriber/rate_limit.py` |
| `minio` | stock `minio/minio`, no custom Dockerfile | Shared S3-compatible object storage for recording audio/transcripts - see `voice_transcriber/storage/` |
| `migrate` | same image as `web` | One-shot: applies Alembic migrations, then exits. `web` waits for this to succeed before starting - see "Migrations" below |
| `web` | built from the repo root `Dockerfile` (its default `backend` target) | API/WS only - `/api/*`, `/ws`, `/ws/translate`, `/healthz`. No page-serving. Stateless - safe to run multiple replicas of, see "Scaling" |
| `nginx` | built from `frontend/Dockerfile` (nginx) | TLS termination, routing (`/api/*`/`/healthz`/`/ws*` to `web`, everything else served locally), security headers, and the SPA shell/login page/static assets - see `frontend/nginx.conf` |
| `certbot` | stock `certbot/certbot`, no custom Dockerfile | Obtains and renews the Let's Encrypt certificate `nginx` serves - see §2's "First-boot TLS bootstrap" |

See also: `README.md`'s "Production" section (how to run it); under
`docs/audits/`, the `SCALABILITY_AUDIT.md`/`SCALABILITY_DESIGN.md`/
`HORIZONTAL_SCALABILITY_READINESS.md` trio (the horizontal-scaling work and
its verification status) and `E2E_Review.md` (open architectural items); and
`docker-compose.prod.yml` plus `frontend/nginx.conf` (the actual configs,
both commented inline).

---

## 1. Environment variables

Set these in `.env.production` (`cp .env.production.example .env.production`,
then fill in real values). Never commit real values — the file is
git-ignored.

| Variable | Required? | Production example | What breaks if it's wrong |
|---|---|---|---|
| `DOMAIN` | Required | `app.example.com` | Used by `scripts/init-letsencrypt.sh` and the `certbot` service's `-d` flag. Must also be hand-edited into `frontend/nginx.conf` (see that file's header comment) - left mismatched between the two, certbot requests a cert for a domain nginx isn't configured to answer for. |
| `CERTBOT_EMAIL` | Required | *(a monitored address)* | Let's Encrypt's only channel for expiry/registration notices. Unlike Caddy's old automatic renewal, a broken `certbot` renewal loop here fails silently otherwise - this email is the one warning you get before the cert lapses. |
| `ENV` | Required | `production` | Wrong/unset → app boots in `development` mode: generated JWT secret, auto-created admin with a printed password, every fail-fast guard below silently skipped. No startup error, because dev mode is a *valid* mode. See README's ".env.production reaches the container" section for how this actually gets set under Compose — it is not simply "put ENV=production in the file." |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Required (Compose path) | `zenoscribe` / *(strong, generated)* / `zenoscribe` | Used by `docker-compose.prod.yml` for both the `db` container and to build `web`'s `DATABASE_URL`. Left at the `zenoscribe`/`zenoscribe` dev default (public in this repo's git history) → production database is reachable with a publicly known password to anyone who can reach port 5432. Firewall it regardless (see §3) — this is defense in depth, not a substitute. |
| `DATABASE_URL` | Required (non-Compose path only) | `postgresql://user:pass@host:5432/zenoscribe` | Missing → app refuses to start (fail-fast in `config.py`). Not needed if using `docker-compose.prod.yml`, which derives it from the three vars above. |
| `SONIOX_API_KEY` | Required | *(from console.soniox.com)* | Missing → app refuses to start. Wrong/expired/revoked → app boots fine, passes health checks, then throws on the first user who hits record — a generic 500 with nothing in the app logs pointing at the real cause. Test it end-to-end (§7/gate item) before calling the deploy done. |
| `JWT_SECRET` | Required | 48-byte random string, `python -c "import secrets; print(secrets.token_urlsafe(48))"` | Missing → app refuses to start. Set once, keep stable — rotating it later force-logs-out every user (sometimes desired, e.g. after a suspected leak, but not routine). |
| `REDIS_URL` | Required | `redis://redis:6379/0` (matches `docker-compose.prod.yml`'s `redis` service) | Missing → app refuses to start. Backs shared rate-limit counters (`rate_limit.py`) — with more than one `web` replica, this is what keeps a per-user limit from effectively multiplying by replica count. Never durable data; losing Redis loses nothing except a brief window of freshly-reset counters. Never expose its port publicly. |
| `STORAGE_BACKEND` | Required, must be `minio` | `minio` | Missing or `local` → app refuses to start. `local` writes recordings to the container's own disk, invisible to any other `web` replica — see `docs/audits/SCALABILITY_AUDIT.md` finding F1. |
| `MINIO_ENDPOINT` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` / `MINIO_BUCKET` / `MINIO_SECURE` | `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY` required when `STORAGE_BACKEND=minio` | `minio:9000` / *(strong, generated)* / *(strong, generated)* / `zenoscribe-recordings` / `false` | Missing access/secret key → app refuses to start. `docker-compose.prod.yml`'s `minio` service reads the same two vars (as `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`) so the two never drift apart. Never expose MinIO's API/console ports publicly. |
| `ADMIN_USERNAME` | Optional | `admin` | Just the seeded first-admin username; harmless to leave default. |
| `ADMIN_PASSWORD` | Required (first boot only) | strong password, ≥8 chars | Missing/weak → app refuses to start *if no admin exists yet* (i.e. blocks first boot only — irrelevant on every later restart once an admin row exists). |
| `TOKEN_HOURS` | Optional | `8` | How long a login lasts before re-auth is required. No safety implication either way, just session-length UX. |
| `SERVER_BOOT_ID` | **Required** | a fixed generated string, e.g. another `token_urlsafe(16)` | Missing → app refuses to start. Promoted from "strongly recommended" once multi-replica became a supported topology: **left unset, each replica would generate its own random value, and a token issued by one replica would be rejected by another** — every user would see random 401s depending on which replica a load balancer routed them to (`docs/audits/SCALABILITY_AUDIT.md` finding F3), independent of whether `JWT_SECRET` stays fixed. Set it once, the same value in every replica's environment; there's still no way to revoke one specific session early (§4, limitations). |
| `DB_POOL_MAX_SIZE` | Optional | `10` | Postgres connection pool size **per replica** (`db.py`). Total connections against Postgres ≈ replica count × this value — shrink it as you add replicas so you don't exceed Postgres's `max_connections` (default 100). See "Scaling" below for a worked example. |
| `GRACEFUL_SHUTDOWN_GRACE_SEC` | Optional | `30` | How long a replica waits, on SIGTERM, for active live transcription/translation sessions to finish and persist their recording before exiting (`server.py`, `live_sessions.py`). Must be shorter than `web`'s `stop_grace_period` in `docker-compose.prod.yml` (default `40s`) or Docker SIGKILLs the process before this wait completes — keep the two in sync if you change either. |
| `ALLOW_TEST_HOOKS` | Must be `false` | `false` | App refuses to start if `true` in production — this is a safeguard already in code, this row is just confirming intent. Test hooks simulate upstream failures; never wanted in production. |
| `TEST_HOOK_SECRET` | Leave blank | *(blank)* | Only meaningful when `ALLOW_TEST_HOOKS=true`, which production refuses anyway. |
| `RESTRICT_TEST_HOOK_TO_LOCALHOST` | Leave `true` | `true` | Same — irrelevant once `ALLOW_TEST_HOOKS` is (correctly) `false`. |
| `DEBUG_TOKENS` | Must be `false` | `false` | If `true`, logs token text — which may contain user speech — into application logs. Not fail-fast enforced in code; this is a "don't" via written policy, not a guard. |
| `DEV_ROTATE_JWT_ON_RESTART` | Leave `false` | `false` | Ignored in production regardless of value; keep `false` for clarity. |
| `SONIOX_UPLOAD_TIMEOUT` / `SONIOX_POLL_REQUEST_TIMEOUT` / `SONIOX_TRANSCRIPTION_INIT_TIMEOUT` | Optional | defaults in `.env.production.example` | Network timeouts to Soniox. Only worth touching if you see spurious timeouts against your production network path. |


### How `ENV` and `.env.production` actually reach the process

`config.py` loads `.env.<ENV>` (e.g. `.env.production`) if it exists, falling
back to plain `.env`. **`ENV` itself must already be a real process
environment variable** - the app has to know which `ENV` it's in before it can
know which file to load, so `ENV=production` written *inside*
`.env.production` is a no-op on some paths. What counts as "real" depends on
how you start the app:

- **Bare `uvicorn`/`python`, no container** - set it on the process directly:
  `ENV=production uvicorn ...`. Putting it in `.env.production` does nothing
  here; nothing has told the process to load that file yet.
- **`docker-compose.prod.yml`** - `web`'s `env_file: .env.production` line
  injects every line of that file, `ENV=production` included, as real
  container process env vars before the app starts. You do **not** also need
  `-e ENV=production`. This is a different mechanism from the top-level
  `--env-file .env.production` flag on the `docker compose` command line,
  which only affects `${VAR}` substitution inside the YAML itself (e.g.
  `${POSTGRES_USER}`) - see this repo's `docker-compose.prod.yml` header
  comment. Both point at the same file; they do different jobs, and both are
  needed.
- **Plain `docker run`** - neither applies. Pass
  `--env-file .env.production -e ENV=production` explicitly.

Getting this wrong is what silently starts the app in `development` mode: a
generated JWT secret, an auto-created admin, and every production fail-fast
guard bypassed - with no startup error, because `development` is a valid mode.
§7's gate checklist proves it didn't happen (blank out `JWT_SECRET` and
confirm the app refuses to start).

### Single combined container (no Compose)

Supported, but you own TLS, and Postgres/Redis/MinIO have to be reachable from
this container by real endpoints (`DATABASE_URL`/`REDIS_URL`/`MINIO_*` in
`.env.production`) - there's no Compose network resolving service names here.
A bare `docker build .` produces the lean backend-only image (the Dockerfile's
default target), so this path needs the combined target named explicitly:

```bash
docker build --target backend-with-frontend -t zenoscribe .
docker run -p 8000:8000 -e ENV=production --env-file .env.production zenoscribe
```

`STORAGE_BACKEND` must still be `minio` - the app refuses to start with
`local`, which isn't shared across anything. No recordings volume is needed:
the only thing the container writes locally is an ephemeral live-session
scratch file, gone when that session ends (`config.live_scratch_dir()`);
durable data lives in MinIO and Postgres, both external to the container.

Both this image and the default `backend` image run as a non-root user
(`USER app` in the Dockerfile) with `--workers 1` pinned deliberately - see
the Dockerfile's comments for why raising the worker count per container is
unsafe without further changes. Scale by running more containers instead (§5).

---

## 2. Runbook

**First-boot TLS bootstrap.** Before the very first `docker compose ... up
-d`, run `./scripts/init-letsencrypt.sh` once (after filling in `DOMAIN`/
`CERTBOT_EMAIL` in `.env.production` and hand-editing the domain into
`frontend/nginx.conf`, per that file's header comment). This exists to
break a chicken-and-egg problem: `nginx`'s TLS server block needs a
certificate file just to start, but certbot can only obtain a real one by
having `nginx` already up and serving the ACME challenge on port 80. The
script writes a throwaway self-signed cert, starts `nginx` on it, requests
the real certificate from Let's Encrypt, then reloads `nginx` onto it.
Not needed again after that — the `certbot` service's own renew loop and
`nginx`'s periodic self-reload (both in `docker-compose.prod.yml`) keep the
certificate current from then on, unmonitored unless you set up the check
described in §3.

**First boot.** Before `web` ever starts, the `migrate` service runs
`db.init()` (all Alembic migrations) to completion — `web`'s `depends_on`
requires this to succeed first (`docker-compose.prod.yml`). Once `web` is
up, its own startup hook creates one admin user from
`ADMIN_USERNAME`/`ADMIN_PASSWORD` via `auth.ensure_seed_admin()` — but
*only* if no admin exists yet in the DB. Log in as that admin and create
real user accounts from the admin console; there's no other user-creation
path.

**Migrations are an explicit, one-time deploy step — not run by `web` at
all.** This changed from the previous "auto-apply on every startup"
behavior once more than one `web` replica became a supported topology:
concurrent, uncoordinated `alembic upgrade head` calls from several
replicas starting at once could race against the same database
(`docs/audits/SCALABILITY_AUDIT.md` finding F4). Now, `docker compose ... up` runs
`migrate` to completion first (it exits 0 and stays stopped — this is
expected, not a crash), and `web`'s own startup hook only *verifies* the
schema is already at the exact revision the code expects
(`db.verify_schema_current()`), refusing to serve traffic otherwise. A bad
migration is still applied the moment `migrate` runs — this doesn't add an
approval gate — but it does mean `web` will now fail loudly and immediately
if a deploy's migration step was skipped or only partially completed,
instead of silently serving requests against the wrong schema. Plan
releases accordingly (e.g. test the image against a staging DB copy first)
rather than expecting a pause point in production.

**Volume inventory** (`docker-compose.prod.yml`):
- `pgdata` — Postgres data directory. Loss = loss of all users, recordings
  metadata, and login history.
- `miniodata` — MinIO's data directory (mounted in the `minio` service).
  Loss = loss of every recording's audio and transcript object ever
  stored. The DB row survives (it's in `pgdata`) but points at an object
  that no longer exists — see "drift" below. `web` itself has **no**
  recordings volume any more — the only thing it ever writes locally is an
  ephemeral live-session scratch file (`config.live_scratch_dir()`), gone
  the moment that session ends; nothing there needs to survive a restart.
- `certbot_conf` / `certbot_www` — the Let's Encrypt certificate, account
  key, and renewal state (`certbot_conf`), plus the ACME HTTP-01 challenge
  webroot `nginx` and `certbot` share (`certbot_www`). Loss of
  `certbot_conf` means re-running `scripts/init-letsencrypt.sh` to
  re-issue from scratch (rate limits apply if this happens repeatedly in a
  short window — not a data emergency, just avoid churning it).
- `redis` has **no volume at all, by design** — it holds only rate-limit
  counters (`rate_limit.py`), never durable data. Losing it (restart,
  crash) just means a brief window of freshly-reset counters.

**Backup.**
- Postgres: `pg_dump` on a schedule, stored *off* the VM. Nothing in this
  repo automates this — set up your own cron/systemd timer.
  ```bash
  docker compose -f docker-compose.prod.yml exec -T db \
    pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup-$(date +%F).sql
  ```
- Recordings: back up the MinIO data using its own client (`mc`), mirroring
  the bucket to an off-host destination — e.g. another `mc`-compatible
  target, or a plain directory you then ship off the VM:
  ```bash
  # One-time: point mc at this deployment's MinIO
  docker run --rm --network container:$(docker compose -f docker-compose.prod.yml ps -q minio) \
    minio/mc alias set zenoscribe http://localhost:9000 "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"
  # Mirror the bucket out to a local directory (swap for a remote mc alias
  # to back up off-host directly)
  docker run --rm --network container:$(docker compose -f docker-compose.prod.yml ps -q minio) \
    -v "$PWD/minio-backup-$(date +%F)":/backup \
    minio/mc mirror zenoscribe/zenoscribe-recordings /backup
  ```
  A plain `docker run ... tar` of the `miniodata` volume (like the old
  recordings-volume backup) also works as a cruder alternative, but won't
  give you object-level restore/consistency checks the way `mc mirror` does.
- **Restore the two together, not independently.** A DB restored from
  Tuesday's backup alongside a MinIO bucket restored from Thursday's will
  disagree — DB rows pointing at objects that don't exist yet, or objects
  with no matching row. Restore both from backups taken at (as close to)
  the same time, then run the reconciliation script below to check.

**Reconciling drift.** `scripts/reconcile_recordings.py` is backend-agnostic
(works against `STORAGE_BACKEND=local` or `=minio`) and finds stored
objects with no matching DB row, and DB rows pointing at missing objects —
exactly the state a partial restore, or a crash mid-write, can produce.
Dry-run by default:
```bash
docker compose -f docker-compose.prod.yml exec web \
  python scripts/reconcile_recordings.py            # report only
docker compose -f docker-compose.prod.yml exec web \
  python scripts/reconcile_recordings.py --delete   # also delete orphan objects
```
It never touches the DB or deletes a DB row — a row pointing at a missing
object is reported only, since guessing which object it should have
pointed to isn't safe to automate.

**Rollback.** Both existing migrations have a working `downgrade()`. To roll
back a release:
1. Stop `web` and `nginx`: `docker compose -f docker-compose.prod.yml stop web nginx`
2. Check out the previous release's code/images.
3. Downgrade one revision: `alembic downgrade -1` (run inside a container
   with the previous code, against the same `DATABASE_URL`) — or to a
   specific revision: `alembic downgrade <revision>`.
4. Start both on the previous images: `docker compose -f docker-compose.prod.yml up -d web nginx`
   (roll back together — a mismatched pair can mean the SPA shell references
   a bundle/route the running backend doesn't have, or vice versa). `web`
   will refuse to start if its `db.verify_schema_current()` check finds the
   schema doesn't match what the checked-out code expects — that's the
   guard working as intended, not a bug; it means the downgrade step above
   needs to actually run first.

**Restart behaviour.** `SERVER_BOOT_ID` is now a required, fixed value
(§1) — restarting a `web` replica (`docker compose restart web`, a crash, a
host reboot) no longer logs out every currently-logged-in user, as long as
every replica shares the same value (the normal case: they all read it from
the same `.env.production`). On SIGTERM, a replica also drains gracefully
for up to `GRACEFUL_SHUTDOWN_GRACE_SEC` (default 30s): it stops accepting
new requests/WS connections immediately (`/healthz` reports
`shutting_down`), asks any active live transcription/translation session to
wrap up and persist its recording, then exits — see `server.py`/
`live_sessions.py`. **This graceful-drain behavior is UNVERIFIED against a
real SIGTERM/real active session** — it was implemented and unit-tested at
the bookkeeping level (`live_sessions.py`), but this environment has no way
to open a real live WebSocket session and send a real SIGTERM to prove the
recording survives intact end-to-end. Test this on your VM before relying
on it: start a live recording, run `docker compose -f
docker-compose.prod.yml kill -s SIGTERM web` (or `restart`), and confirm
the recording appears intact (not truncated/corrupted) in "My recordings"
afterward.

---

## 3. Their scope (yours) — generate and hold

- **All production secrets.** A fresh `JWT_SECRET`
  (`python -c "import secrets; print(secrets.token_urlsafe(48))"`), a
  **newly issued** production `SONIOX_API_KEY` from console.soniox.com —
  not the developer's dev key — and a strong `ADMIN_PASSWORD`. Confirm
  `ALLOW_TEST_HOOKS=false` and `DEBUG_TOKENS=false`.
- **TLS, DNS, the domain.** Non-negotiable: browsers block `getUserMedia`
  (microphone capture) outside a secure context, so recording and
  translation simply do not function over plain HTTP on a real domain.
  Point DNS at the VM, set `DOMAIN`/`CERTBOT_EMAIL` in `.env.production`
  and hand-edit the same domain into `frontend/nginx.conf`, then run
  `./scripts/init-letsencrypt.sh` once (§2). After that, `certbot` renews
  automatically — but unlike Caddy, it won't warn you if that stops
  working. **Set up a certificate-expiry monitoring check** (e.g. a cron
  hitting `openssl s_client -connect $DOMAIN:443 -servername $DOMAIN
  </dev/null 2>/dev/null | openssl x509 -noout -enddate`, alerting if
  under ~14 days remain) — nothing in this repo does this for you.
- **Firewall.** Only 80/443 should be publicly reachable. Ports 8000
  (`web`), 5432 (`db`), 6379 (`redis`), and 9000/9001 (`minio`) must not be
  exposed — `docker-compose.prod.yml` already keeps all four off the host
  via `expose:` instead of `ports:` (or no ports entry at all), but confirm
  at the VM/cloud firewall layer too; don't rely on Compose alone.
- **VM hardening** — SSH policy (keys only, no root login), unattended
  security upgrades, OS patching cadence.
- **Database backups** — see §2. Nothing in this repo implements
  scheduling; that's yours.
- **MinIO (recordings) backup** — see §2, and restore together with the DB.
- **Disk monitoring.** Recordings/transcripts in MinIO grow without bound —
  there is no retention/deletion policy in the app. Watch `miniodata`'s
  disk usage on the VM.
- **Monitoring and alerting** against `GET /healthz` (§1 of README's
  Production section describes the response shape). Make sure it pages a
  human — Docker's `restart: unless-stopped` only retries on container
  *exit*, not on a failed healthcheck, so a sustained DB outage leaves `web`
  running and quietly serving 503s/500s rather than restarting or alerting
  on its own.
- **Image registry.** `docker-compose.prod.yml` builds `web` and `frontend`
  from source; nothing here pushes either image to a registry. Rollback
  today means checking out the previous release and rebuilding both (works,
  per §2, but slower and more error-prone mid-incident than an instant image
  swap). Push tagged images to a registry (GHCR/ECR/etc.) if faster rollback
  matters.

---

## 4. Known limitations — not defects, deliberate scope

- **`web` can now run multiple replicas** (see "Scaling" below) - recording
  storage (MinIO), rate limiting (Redis), and session validity
  (`SERVER_BOOT_ID`, now a required shared value) are all shared across
  replicas. This is new; see `docs/audits/SCALABILITY_AUDIT.md`/`docs/audits/SCALABILITY_DESIGN.md`/
  `docs/audits/HORIZONTAL_SCALABILITY_READINESS.md` for exactly what was changed, what
  was verified, and what remains UNVERIFIED without a real multi-container
  run on your VM. Docker itself is available in this repo's tool environment
  as of 2026-08-25 (confirmed working against the **dev** stack,
  `docker-compose.yml`) - what's still unrun is `docker-compose.prod.yml`
  specifically, multi-replica or otherwise; see
  `docs/audits/DEPLOYMENT_READINESS_AUDIT.md`'s P1-B. `db` and `redis`/`minio`
  themselves are each still a single instance - see "If you scale beyond
  one VM" below for what that does and doesn't cover.
- **Single uvicorn worker per container**, pinned explicitly in the
  Dockerfile. This is still load-bearing - raising `--workers` inside one
  container would give each worker its own in-memory turn-detection state
  with no coordination, which is a different problem than the
  now-solved cross-*container* replica case. Scale by adding more
  containers (replicas), not more workers per container.
- **No token revocation / no logout endpoint.** The only ways to kill a
  session early are deactivating the user or rotating `SERVER_BOOT_ID`
  (which invalidates *every* session across every replica, not just one).
- **20 MB upload ceiling** (`config.MAX_UPLOAD_MB`; `frontend/nginx.conf`'s
  `client_max_body_size` is set slightly above this so the app's own
  limit is always what actually rejects an oversized file, with a clear
  message).
- **`CREATE EXTENSION citext`** in the initial migration needs elevated
  Postgres privileges. Fine against the Compose-managed Postgres in this
  repo (superuser by default); it will fail against a managed Postgres
  instance (RDS, Cloud SQL, etc.) unless the extension is pre-installed or
  your DB user has been granted rights to create it. Flag this now if you
  intend to move the database off the VM onto a managed service.
- **Mobile is untested on real hardware** — verified via code, automated
  test suites, and a production build only, not an actual iPhone/Android in
  hand.
- **No load or soak testing has been performed.**

---

## 5. Scaling `web` beyond one replica

Plain Docker Compose, no Swarm/Kubernetes needed - Compose's own `--scale`
flag runs multiple containers of the same service:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml \
  up -d --scale web=3
```

This works today because `web` is stateless: recordings go to the shared
`minio` service (not a per-container volume), rate limits are enforced via
the shared `redis` service (not an in-memory counter), and every replica
validates the same `SERVER_BOOT_ID` (a required, shared env var — no more
per-process random values). `frontend/nginx.conf`'s `resolver`/`$backend`
directives are what make nginx actually spread requests across however many
replicas Docker's embedded DNS reports, instead of pinning to whichever one
resolved first — see that file's comment and `docs/audits/SCALABILITY_AUDIT.md` finding
F7 for why that would otherwise silently *not* work with a bare
`proxy_pass http://web:8000`.

**This has not been run for real in this environment** — Docker itself is
now available (installed 2026-08-25) and the **dev** stack
(`docker-compose.yml`) has been run end to end on it, but this specific
multi-replica `docker-compose.prod.yml --scale` scenario has not; it's been
reasoned through against the actual code and Docker/nginx's documented
behavior, not observed. Before trusting it in production, run the
multi-replica validation in `docs/audits/HORIZONTAL_SCALABILITY_READINESS.md` on your
VM: bring up 3 replicas, confirm login/recordings/downloads work regardless
of which replica answers, confirm a shared rate limit actually holds across
all three, and confirm killing one replica doesn't disrupt users on the
others.

**Scaling down** works the same way: `--scale web=1` (or any smaller
number) — Compose stops the excess containers. A replica mid-shutdown
drains gracefully (see "Restart behaviour" in §2) before Compose considers
it stopped, up to `GRACEFUL_SHUTDOWN_GRACE_SEC`/`stop_grace_period`.

**`DB_POOL_MAX_SIZE` sizing** (§1) — each replica opens its own Postgres
connection pool; total connections against `db` is approximately
`replica_count × DB_POOL_MAX_SIZE`. Postgres's default `max_connections` is
100. Leave headroom for the one-shot `migrate` service and any manual
`psql`/admin connections:

| Replicas | Suggested `DB_POOL_MAX_SIZE` | Approx. total connections |
|---|---|---|
| 1 (default) | 10 | ~10 |
| 3 | 10 | ~30 |
| 5 | 8 | ~40 |
| 10 | 6 | ~60 |

Beyond ~10 replicas on a single default-configured Postgres instance,
either raise Postgres's own `max_connections` (with the memory-per-connection
cost that implies) or introduce connection pooling in front of Postgres
(e.g. PgBouncer) — not implemented in this repo, flagged here as the next
step if you outgrow this table.

**Workers.** There is no background job queue/worker fleet in this
architecture, deliberately — see `docs/audits/SCALABILITY_DESIGN.md` §1 for why: batch
upload transcription already scales linearly with replica count via its own
per-process bounded thread pool (`routes_api.py`'s `_UPLOAD_EXECUTOR`), and
live transcription/translation is an inherently synchronous bidirectional
stream that has nothing to meaningfully queue. Nothing to configure here.

**If you scale beyond one VM.** `db`/`redis`/`minio` are each still a
single instance/single disk on this one VM — none of them have been made
highly available by this work, only `web` has. Distinguish these clearly
when reasoning about failure modes:
- **API horizontal scaling** — done (this section), same VM, multiple `web`
  containers.
- **Database HA** — not done. `db` is one Postgres instance; its loss is
  still a full outage until restored from backup. Postgres streaming
  replication / a managed HA Postgres is the next step if this matters to
  you, out of scope here.
- **Redis HA** — not attempted, and arguably not worth it: Redis here holds
  only reconstructible rate-limit counters, so a Redis outage degrades to
  fail-closed 503s on rate-limited routes (see `rate_limit.py`) rather than
  losing anything, and recovers itself the moment Redis comes back.
- **MinIO HA** — not done. A single MinIO instance/single disk is not
  redundant storage — see MinIO's own docs on distributed mode (multiple
  nodes, multiple disks, erasure coding) if you need this; not implemented
  here.
- **VM HA** — not done. This is still a single-VM deployment; the VM itself
  is a single point of failure for `db`, `redis`, and `minio` regardless of
  how many `web` replicas run on it.

---

## 6. Known issues

Full evidence, file:line citations, and the complete current finding set
(P0/P1/P2/Notes, verified vs. unverified) live in
`docs/audits/DEPLOYMENT_READINESS_AUDIT.md`. That doc used to be a frozen dated snapshot
with this section carrying the live fixed/open status separately — as of
2026-08-24 it's rewritten in place instead, so it's now the one evergreen
source for "is this finding still open," and this section is no longer
duplicated here. The two operational items it currently flags as open —
recordings disk-growth monitoring and certificate-expiry monitoring — are
also tracked in §3 below.

---

## 7. Gate — run before calling a deploy done

- [ ] **Clean-clone test.** Fresh `git clone` into an empty directory,
      `.env.production` filled in, `docker compose --env-file
      .env.production -f docker-compose.prod.yml up -d --build`. Must come
      up with no manual intervention and no step that exists only in
      someone's shell history.
- [ ] **Prove `ENV=production` actually took effect** — the single
      highest-value check here. Temporarily blank `JWT_SECRET` and confirm
      the app *refuses to start*. If it boots, it's running in development
      mode and every guard in §1 is silently off.
- [ ] **Confirm no `.env` file is inside the built backend image**:
      `docker run --rm <web image> ls -la /app` should show nothing but
      `.env.example`/`.env.production.example` — no real `.env`/`.env.production`
      (CI's `docker-build` job checks this automatically on every push — see
      `.github/workflows/ci.yml`). `frontend`'s image has no equivalent risk —
      its build only ever copies `frontend/` into the build stage.
- [ ] **Container-replacement test.** `docker compose -f
      docker-compose.prod.yml down && up -d` — recordings and users must
      survive (this is exactly what the named volumes exist to guarantee;
      the only way to know they're wired right is to try it), and all seven
      services (`db`, `redis`, `minio`, `migrate`, `web`, `nginx`,
      `certbot`) must come back healthy (`migrate` exits 0 and stays
      stopped — that's success, not a crash).
- [ ] **Confirm `STORAGE_BACKEND`/`REDIS_URL`/`SERVER_BOOT_ID` guards fire**
      the same way the `JWT_SECRET` check above does: temporarily set
      `STORAGE_BACKEND=local` (or blank `REDIS_URL`/`SERVER_BOOT_ID`) and
      confirm `web` refuses to start each time, then restore the real values.
- [ ] **Multi-replica validation, if you intend to run more than one `web`
      replica** — see §5's "Scaling" section and
      `docs/audits/HORIZONTAL_SCALABILITY_READINESS.md` for the exact procedure. This is
      new, UNVERIFIED-until-you-run-it work; don't skip it just because a
      single replica passed the rest of this gate.
- [ ] **Restart behaviour on an active session** — see §2's "Restart
      behaviour": confirm a `SERVER_BOOT_ID`-pinned restart doesn't log
      users out, and confirm a SIGTERM during a live recording persists it
      intact (both UNVERIFIED in this repo's own tool environment - see
      that section).
- [ ] **End-to-end over real TLS**, not localhost: login, live record,
      translate, upload, download a transcript. Mic capture cannot be
      validated any other way — `localhost` is exempt from the secure-context
      requirement, so a localhost-only test proves nothing about the real
      domain. While here, confirm the served certificate is genuinely
      Let's Encrypt-issued, not `scripts/init-letsencrypt.sh`'s bootstrap
      self-signed one — browsers show this clearly (padlock, no warning);
      `openssl s_client -connect $DOMAIN:443 -servername $DOMAIN
      </dev/null 2>/dev/null | openssl x509 -noout -issuer` also confirms it.
- [ ] **Full test suite green** on the exact commit deployed:
      `python -m flake8 voice_transcriber scripts --max-line-length=120`,
      `python -m pytest -q`, `python -m pytest -q -m integration` (the real
      Playwright E2E suite - needs Postgres/Redis reachable and Playwright
      browsers installed), `npm --prefix frontend run build`,
      `npm --prefix frontend test`.
- [ ] **Tag the release** you deploy — reference that tag in tickets/incident
      reports, not "whatever was on main."
