# Zenoscribe — Deployment Guide

For the deployment team. Target: a single Ubuntu VM, Docker Compose, Caddy
in front for TLS. Replaces `Req._deployment.txt`, which predated the
Compose + Caddy setup — this is the one current doc, don't split back into
two.

See also: `README.md`'s "Production" section (how to run it),
`E2E_Review.md` (open architectural items), `docker-compose.prod.yml` and
`Caddyfile` (the actual configs, both commented inline).

---

## 1. Environment variables

Set these in `.env.production` (`cp .env.production.example .env.production`,
then fill in real values). Never commit real values — the file is
git-ignored.

| Variable | Required? | Production example | What breaks if it's wrong |
|---|---|---|---|
| `ENV` | Required | `production` | Wrong/unset → app boots in `development` mode: generated JWT secret, auto-created admin with a printed password, every fail-fast guard below silently skipped. No startup error, because dev mode is a *valid* mode. See README's ".env.production reaches the container" section for how this actually gets set under Compose — it is not simply "put ENV=production in the file." |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Required (Compose path) | `zenoscribe` / *(strong, generated)* / `zenoscribe` | Used by `docker-compose.prod.yml` for both the `db` container and to build `web`'s `DATABASE_URL`. Left at the `zenoscribe`/`zenoscribe` dev default (public in this repo's git history) → production database is reachable with a publicly known password to anyone who can reach port 5432. Firewall it regardless (see §3) — this is defense in depth, not a substitute. |
| `DATABASE_URL` | Required (non-Compose path only) | `postgresql://user:pass@host:5432/zenoscribe` | Missing → app refuses to start (fail-fast in `config.py`). Not needed if using `docker-compose.prod.yml`, which derives it from the three vars above. |
| `SONIOX_API_KEY` | Required | *(from console.soniox.com)* | Missing → app refuses to start. Wrong/expired/revoked → app boots fine, passes health checks, then throws on the first user who hits record — a generic 500 with nothing in the app logs pointing at the real cause. Test it end-to-end (§6/gate item) before calling the deploy done. |
| `JWT_SECRET` | Required | 48-byte random string, `python -c "import secrets; print(secrets.token_urlsafe(48))"` | Missing → app refuses to start. Set once, keep stable — rotating it later force-logs-out every user (sometimes desired, e.g. after a suspected leak, but not routine). |
| `ADMIN_USERNAME` | Optional | `admin` | Just the seeded first-admin username; harmless to leave default. |
| `ADMIN_PASSWORD` | Required (first boot only) | strong password, ≥8 chars | Missing/weak → app refuses to start *if no admin exists yet* (i.e. blocks first boot only — irrelevant on every later restart once an admin row exists). |
| `TOKEN_HOURS` | Optional | `8` | How long a login lasts before re-auth is required. No safety implication either way, just session-length UX. |
| `SERVER_BOOT_ID` | **Strongly recommended** | a fixed generated string, e.g. another `token_urlsafe(16)` | **Left unset: every restart — not just a redeploy, also a crash loop, `docker compose restart`, a host reboot — force-logs-out every user**, independently of `JWT_SECRET` staying fixed. See README's `SERVER_BOOT_ID` section for the mechanism. Set it once to a fixed value if you don't want routine restarts to log everyone out; there's no way to revoke one specific session either way (§4, limitations). |
| `ALLOW_TEST_HOOKS` | Must be `false` | `false` | App refuses to start if `true` in production — this is a safeguard already in code, this row is just confirming intent. Test hooks simulate upstream failures; never wanted in production. |
| `TEST_HOOK_SECRET` | Leave blank | *(blank)* | Only meaningful when `ALLOW_TEST_HOOKS=true`, which production refuses anyway. |
| `RESTRICT_TEST_HOOK_TO_LOCALHOST` | Leave `true` | `true` | Same — irrelevant once `ALLOW_TEST_HOOKS` is (correctly) `false`. |
| `DEBUG_TOKENS` | Must be `false` | `false` | If `true`, logs token text — which may contain user speech — into application logs. Not fail-fast enforced in code; this is a "don't" via written policy, not a guard. |
| `DEV_ROTATE_JWT_ON_RESTART` | Leave `false` | `false` | Ignored in production regardless of value; keep `false` for clarity. |
| `SONIOX_UPLOAD_TIMEOUT` / `SONIOX_POLL_REQUEST_TIMEOUT` / `SONIOX_TRANSCRIPTION_INIT_TIMEOUT` | Optional | defaults in `.env.production.example` | Network timeouts to Soniox. Only worth touching if you see spurious timeouts against your production network path. |

---

## 2. Runbook

**First boot.** On first startup with an empty database, `db.init()` runs
all Alembic migrations, then `auth.ensure_seed_admin()` creates one admin
user from `ADMIN_USERNAME`/`ADMIN_PASSWORD` — but *only* if no admin exists
yet in the DB. Log in as that admin and create real user accounts from the
admin console; there's no other user-creation path.

**Migrations auto-apply at startup, every startup** — `db.init()` runs
unconditionally, idempotently, in-process, before the app starts serving
traffic. There is no manual approval gate. A bad migration in a future
release applies itself the moment the new image starts. This is a known,
accepted limitation (§4) — plan releases accordingly (e.g. test the image
against a staging DB copy first) rather than expecting a pause point in
production.

**Volume inventory** (`docker-compose.prod.yml`):
- `pgdata` — Postgres data directory. Loss = loss of all users, recordings
  metadata, and login history.
- `recordings` — mounted at `/app/voice_transcriber/recordings` in `web`.
  Loss = loss of every `.wav`/`.mp3` and `.txt` transcript ever recorded.
  The DB row survives (it's in `pgdata`) but points at a file that no
  longer exists — see "drift" below.
- `caddy_data` / `caddy_config` — Caddy's TLS certificate/state. Loss just
  means Caddy re-issues a cert from Let's Encrypt on next start (rate
  limits apply if this happens repeatedly in a short window — not a data
  emergency, just avoid churning it).

**Backup.**
- Postgres: `pg_dump` on a schedule, stored *off* the VM. Nothing in this
  repo automates this — set up your own cron/systemd timer.
  ```bash
  docker compose -f docker-compose.prod.yml exec -T db \
    pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup-$(date +%F).sql
  ```
- Recordings: back up the `recordings` volume separately, e.g.
  ```bash
  docker run --rm -v zenoscribe_recordings:/data -v "$PWD":/backup \
    alpine tar czf /backup/recordings-$(date +%F).tar.gz -C /data .
  ```
  (volume name may be prefixed by your Compose project name — check
  `docker volume ls`).
- **Restore the two together, not independently.** A DB restored from
  Tuesday's backup alongside recordings restored from Thursday's will
  disagree — DB rows pointing at files that don't exist yet, or files with
  no matching row. Restore both from backups taken at (as close to) the
  same time, then run the reconciliation script below to check.

**Reconciling drift.** `scripts/reconcile_recordings.py` finds recordings/
files with no matching DB row and DB rows pointing at missing files —
exactly the state a partial restore, or a crash mid-write, can produce.
Dry-run by default:
```bash
docker compose -f docker-compose.prod.yml exec web \
  python scripts/reconcile_recordings.py            # report only
docker compose -f docker-compose.prod.yml exec web \
  python scripts/reconcile_recordings.py --delete   # also delete orphan files
```
It never touches the DB or deletes a DB row — a row pointing at a missing
file is reported only, since guessing which file it should have pointed to
isn't safe to automate.

**Rollback.** Both existing migrations have a working `downgrade()`. To roll
back a release:
1. Stop `web`: `docker compose -f docker-compose.prod.yml stop web`
2. Check out the previous release's code/image.
3. Downgrade one revision: `alembic downgrade -1` (run inside a container
   with the previous code, against the same `DATABASE_URL`) — or to a
   specific revision: `alembic downgrade <revision>`.
4. Start `web` on the previous image: `docker compose -f docker-compose.prod.yml up -d web`

**Restart behaviour.** Restarting the `web` container (`docker compose
restart web`, a crash, a host reboot) logs out every currently-logged-in
user *unless* `SERVER_BOOT_ID` is pinned to a fixed value (§1). This is
expected, documented behaviour, not a bug — decide up front whether that's
acceptable for your users or whether to pin it.

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
  Point DNS at the VM, put the real domain in `Caddyfile`, and Caddy
  handles the certificate automatically.
- **Firewall.** Only 80/443 should be publicly reachable. Ports 8000
  (`web`) and 5432 (`db`) must not be exposed — `docker-compose.prod.yml`
  already keeps `web` off the host via `expose:` instead of `ports:`, and
  `db` has no `ports:` entry at all, but confirm at the VM/cloud firewall
  layer too; don't rely on Compose alone.
- **VM hardening** — SSH policy (keys only, no root login), unattended
  security upgrades, OS patching cadence.
- **Database backups** — see §2. Nothing in this repo implements
  scheduling; that's yours.
- **Recordings volume backup** — see §2, and restore together with the DB.
- **Disk monitoring.** Recordings and WAV files grow without bound — there
  is no retention/deletion policy in the app. Watch disk usage on the VM.
- **Monitoring and alerting** against `GET /healthz` (§1 of README's
  Production section describes the response shape). Make sure it pages a
  human — Docker's `restart: unless-stopped` only retries on container
  *exit*, not on a failed healthcheck, so a sustained DB outage leaves `web`
  running and quietly serving 503s/500s rather than restarting or alerting
  on its own.
- **Image registry.** `docker-compose.prod.yml` builds from source
  (`build: .`); nothing here pushes images to a registry. Rollback today
  means checking out the previous release and rebuilding (works, per §2,
  but slower and more error-prone mid-incident than an instant image swap).
  Push tagged images to a registry (GHCR/ECR/etc.) if faster rollback matters.

---

## 4. Known limitations — not defects, deliberate scope

- **Single container only.** Recordings live on a local Docker volume, so a
  second replica can't see the first's files. Horizontal scaling needs
  S3-compatible object storage (not implemented) and a shared
  `SERVER_BOOT_ID`/rate-limit story (also not implemented — see
  `E2E_Review.md`). Scale vertically instead.
- **Single uvicorn worker**, pinned explicitly in the Dockerfile. Raising it
  gives each worker its own `SERVER_BOOT_ID` (random cross-worker 401s) and
  runs migrations concurrently in every worker on startup.
- **Migrations auto-apply at startup**, no manual gate (§2).
- **No token revocation / no logout endpoint.** The only ways to kill a
  session early are deactivating the user or bouncing `SERVER_BOOT_ID`
  (which bounces *every* session, not just one).
- **20 MB upload ceiling** (`config.MAX_UPLOAD_MB`; `Caddyfile`'s
  `request_body max_size` is set slightly above this so the app's own
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

## 5. Known issues (2026-08-21 readiness audit) — status

Full evidence, file:line citations, and the complete finding set (P0/P1/P2/Notes,
verified vs. unverified) live in `DEPLOYMENT_READINESS_AUDIT.md` — kept as a
separate, dated report rather than merged into this doc, since its findings are
a snapshot against one commit and go stale as they're fixed, while this doc
stays evergreen. Status of that audit's findings as of this doc's last edit:

**Fixed:**
- **Blocking DB/bcrypt calls on the single event loop (P1).** Every direct
  `db.*` call in `routes_api.py` and in `auth.py`'s `current_user`/
  `user_from_token`/`user_from_ws`, plus every `bcrypt.hashpw`/`checkpw`
  call site, and `translate.py`'s WS auth path, now run through
  `asyncio.to_thread` — the same pattern `transcribe.py` already used.
  Verified: full `pytest` suite green post-fix.
- **WebSocket auth had no timeout on the first frame (P2).** Both
  `auth.user_from_ws` (used by `transcribe.py`) and `translate.py` now wrap
  the first `receive_json()` in `asyncio.wait_for(..., timeout=10)`.
- **Unrelated repo content shipped inside the production image (P2).**
  `.dockerignore` now excludes `voice_transcriber/tests/` and
  `voice_transcriber/code_reviews/`.
- **No lint CI gate (P2).** `backend-lint` now runs `flake8` as a blocking
  CI job; the pre-existing violations it caught have been fixed.
- **No container/base-image scan, no Dependabot (P2).** CI's `docker-build`
  job now runs a Trivy scan (`CRITICAL,HIGH`, fails the build) against the
  built image, and `.github/dependabot.yml` opens weekly bump PRs across
  pip, npm, the Dockerfile base image, and GitHub Actions. CodeQL/SAST and
  an SBOM remain backlog, lower urgency than the scan + Dependabot pair.

**Still open (operational, not code — see §3):**
- **Recordings disk growth has no automated alert**, only a documented
  manual watch. ~115MB/hour of WAV per concurrent live session, no
  retention policy anywhere in `scripts/`. Set up a disk-usage alert on the
  VM before turning on real traffic — see §3's "Disk monitoring" bullet.
- **No image registry / instant-rollback path yet** — see §3's "Image
  registry" bullet.

---

## 6. Gate — run before calling a deploy done

- [ ] **Clean-clone test.** Fresh `git clone` into an empty directory,
      `.env.production` filled in, `docker compose --env-file
      .env.production -f docker-compose.prod.yml up -d --build`. Must come
      up with no manual intervention and no step that exists only in
      someone's shell history.
- [ ] **Prove `ENV=production` actually took effect** — the single
      highest-value check here. Temporarily blank `JWT_SECRET` and confirm
      the app *refuses to start*. If it boots, it's running in development
      mode and every guard in §1 is silently off.
- [ ] **Confirm no `.env` file is inside the built image**:
      `docker run --rm zenoscribe ls -la /app` should show nothing but
      `.env.example`/`.env.production.example` — no real `.env`/`.env.production`
      (CI's `docker-build` job checks this automatically on every push — see
      `.github/workflows/ci.yml`).
- [ ] **Container-replacement test.** `docker compose -f
      docker-compose.prod.yml down && up -d` — recordings and users must
      survive (this is exactly what the named volumes exist to guarantee;
      the only way to know they're wired right is to try it).
- [ ] **Restart behaviour on an active session** matches what you decided
      in §1/§2 for `SERVER_BOOT_ID`.
- [ ] **End-to-end over real TLS**, not localhost: login, live record,
      translate, upload, download a transcript. Mic capture cannot be
      validated any other way — `localhost` is exempt from the secure-context
      requirement, so a localhost-only test proves nothing about the real
      domain.
- [ ] **Full test suite green** on the exact commit deployed:
      `python -m flake8 voice_transcriber scripts --max-line-length=120`,
      `python -m pytest -q`, `npm --prefix frontend run build`,
      `npm --prefix frontend test`.
- [ ] **Tag the release** you deploy — reference that tag in tickets/incident
      reports, not "whatever was on main."
