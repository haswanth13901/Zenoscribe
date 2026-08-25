# Zenoscribe — Deployment Readiness Audit

**Verdict: GO WITH CONDITIONS**

*Audited against commit `b44ebb3` (2026-08-24). This document is kept current, not a
dated snapshot — see the note below.*

The fail-closed production guards, ownership checks, and rate limiting all hold up under
direct code and runtime inspection — this is a materially more careful pre-launch
codebase than most, and its own `DEPLOYMENT.md`/`E2E_Review.md` already document several
of the trade-offs an audit would normally have to discover. The DB-layer async-blocking
issue this audit originally flagged (P1-1/P1-2, below) is fixed and verified. The
production edge was rebuilt this same commit (Caddy → nginx + certbot); that rebuild
introduced one real security regression (X-Forwarded-For spoofing, below) which was
caught and fixed in this same audit pass, and it introduces one new condition that
supersedes everything else here: **the new nginx/certbot stack has never actually been
run** (no Docker available in the environment this was built in), so it needs a real
end-to-end verification before go-live in a way the previous Caddy setup already had.
Disk-growth monitoring and certificate-expiry monitoring both remain unwired operational
tasks that must happen before go-live.

> **On keeping this doc current vs. a dated snapshot:** earlier versions of this audit
> (through 2026-08-22) were a frozen snapshot with a separate "Status update" appendix in
> `DEPLOYMENT.md` §5 carrying the live status. That split was intentional at the time, but
> the deploying team decided it was more useful to keep one evergreen readiness doc
> instead of maintaining two. This file is now rewritten in place on each pass; git
> history is where the historical snapshots live if you need them.

---

## P0 blockers

**None found.** No auth bypass, no secret exposure in logs, no data-loss path, and no
guaranteed-outage-in-week-one scenario turned up under direct tracing.

---

## P1 — fix before go-live

### P1-A. [Found and fixed this pass] nginx forwarded a client-spoofable IP instead of its own

**What was wrong:** `frontend/nginx.conf`'s four `proxy_pass` locations (`/api/`,
`/healthz`, `/ws`, `/ws/translate`) set `proxy_set_header X-Forwarded-For
$proxy_add_x_forwarded_for;`. That directive *appends* nginx's observed peer address to
whatever `X-Forwarded-For` value the client already sent, rather than replacing it. A
client could send its own `X-Forwarded-For: 1.2.3.4` and have it preserved as the
left-most entry.

**Why that mattered:** confirmed directly against the installed package —
`uvicorn/middleware/proxy_headers.py:169-187`'s `get_trusted_client_address` returns
`x_forwarded_for_hosts[0]` (the left-most / attacker-supplied entry) whenever
`always_trust` is set, which it is here (`Dockerfile:124` — `--forwarded-allow-ips="*"`).
[voice_transcriber/routes_api.py:86](voice_transcriber/routes_api.py#L86)
(`client_ip = request.client.host`, feeding `count_recent_failed_logins`/
`record_failed_login`) and
[voice_transcriber/rate_limit.py:107-109](voice_transcriber/rate_limit.py#L107-L109)
(`scope.get("client")`, the global per-IP rate limiter) both read exactly the field
`ProxyHeadersMiddleware` overwrites from that header. A forged `X-Forwarded-For` would
have let an attacker evade both the failed-login lockout and the global rate limiter, or
frame another IP for their own abusive traffic.

**Why it's new:** Caddy (the previous edge, removed this same commit) discards any
inbound `X-Forwarded-For` from the client by default and sets a fresh header from only
the connection it directly observed — the original version of this audit traced and
confirmed that exact behavior. nginx has no equivalent default; `$proxy_add_x_forwarded_for`
is the commonly-recommended directive for the *opposite* case (a trusted upstream proxy
chain you want preserved), which doesn't apply here since nginx is the only thing that
can reach `web:8000` at all.

**Fix applied:** `proxy_set_header X-Forwarded-For $remote_addr;` in all four locations —
`$remote_addr` is nginx's own directly-observed peer address, never client-suppliable.
See `frontend/nginx.conf`'s inline comment on the `/ws` block.

**Status: fixed in the working tree, not yet committed** — this needs a commit before
deploy.

### P1-B. The new nginx/certbot production edge has never been executed

**Evidence:** `frontend/nginx.conf` (TLS termination, routing, security headers),
`scripts/init-letsencrypt.sh` (first-boot dummy-cert → real-cert bootstrap), and the
`nginx`/`certbot` services in `docker-compose.prod.yml` were all written and committed in
this same session, entirely without access to Docker (`docker: command not found` in
every environment this was developed in — confirmed again this pass). Verification so far
has been static only: YAML parses, nginx config braces balance, every cross-file
reference is internally consistent, and the logic was reasoned through carefully — but
none of that proves nginx actually starts, that the certbot bootstrap script's dummy-cert
handoff works as written, or that a real Let's Encrypt certificate gets issued.

**Failure scenario:** this is the single edge every request passes through. A mistake
that only manifests at runtime (a typo in a `proxy_pass` target, a missing directory for
the ACME webroot, an off-by-one in the bootstrap script's cert path) would be a
complete-outage or TLS-never-issues failure discovered only on the actual first deploy,
not caught by anything that ran so far.

**Smallest fix:** this doesn't need a code change (the earlier audit pass already
required the P1-A fix above) — it needs the verification DEPLOYMENT.md §6's gate
checklist already asks for, done for real, before this is trusted: build the image, run
`nginx -t`, run `./scripts/init-letsencrypt.sh` against a real domain, and complete the
full HTTPS smoke test (login, live record, translate, upload) over the real domain, not
localhost. Treat this stack as unverified until that happens once.

### P1-C. Unbounded recordings disk growth has no automated monitoring

**Evidence:** [transcribe.py:143-145](voice_transcriber/transcribe.py#L143-L145) — 16kHz,
16-bit, mono PCM WAV ⇒ 32,000 bytes/sec ⇒ **~115MB per concurrent live-session hour**.
`DEPLOYMENT.md` §3 documents this as a manual watch; no cron, alert, or retention job
exists anywhere in `scripts/` (`reconcile_recordings.py` only reconciles DB/file drift,
it doesn't free space).

**Failure scenario:** sustained live usage fills the disk within weeks on a modest VM; at
that point Postgres can't write WAL and `recordings/` writes fail mid-session — silent
data loss (caught broadly and logged, not surfaced to the user) rather than a clean,
alertable failure.

**Smallest fix:** operational, not code — a disk-usage alert on the VM, sized against
expected concurrent-usage hours, set up before go-live. Unchanged since the previous
audit pass.

### P1-D. Certificate-expiry monitoring has no automated check

**Evidence:** this is new as of the nginx/certbot migration, not carried over from the
previous audit. Caddy renewed and retried silently with no equivalent user-facing
failure mode worth monitoring; the `certbot` service (`docker-compose.prod.yml`) now owns
that job instead, and — as documented in `DEPLOYMENT.md` §3 — a broken renewal loop here
gives no warning before the certificate actually lapses and every user starts seeing a
browser TLS error.

**Smallest fix:** operational — `DEPLOYMENT.md` §3 already specifies the check
(`openssl s_client ... | openssl x509 -noout -enddate`, alerting under ~14 days
remaining). Set it up before go-live, same as P1-C.

---

## Fixed (verified, not just doc-claimed)

- **Blocking DB/bcrypt calls on the single event loop — Fixed.** Confirmed directly in
  code, not taken on the doc's word: [auth.py:135](voice_transcriber/auth.py#L135)
  (`await asyncio.to_thread(db.touch_seen, ...)`),
  [routes_api.py:99](voice_transcriber/routes_api.py#L99) (`await
  asyncio.to_thread(auth.verify_password, ...)`), and every other `db.*`/`bcrypt.*` call
  site in `routes_api.py`/`auth.py` now run through `asyncio.to_thread`, matching the
  pattern `transcribe.py` already used. Full `pytest -q`: **81 passed, 21 deselected**,
  re-run this pass.
- **WebSocket auth has no timeout on the first frame — Fixed.** `auth.user_from_ws` and
  `translate.py` wrap the first `receive_json()` in `asyncio.wait_for(..., timeout=10)`.
- **Unrelated repo content shipped inside the production image — Fixed.**
  `.dockerignore` excludes `voice_transcriber/tests/` and `voice_transcriber/code_reviews/`.
- **No lint CI gate — Fixed.** `backend-lint` runs `flake8` as a blocking job; re-run
  this pass, clean.
- **No container/base-image scan, no Dependabot — Fixed.** CI's `docker-build` job runs
  Trivy (`CRITICAL,HIGH`, `exit-code: 1`) against both built images;
  `.github/dependabot.yml` opens weekly bump PRs. Two CVEs are suppressed in
  `.trivyignore`, each with a substantive, re-checked justification, not a bare ID.
- **`sqlalchemy` was an undeclared direct dependency — Fixed this pass.**
  `alembic/env.py:5-6` and every migration file (`script.py.mako:11`, `import sqlalchemy
  as sa`) import it directly, and it runs on every app startup via `db.init()`'s
  `alembic upgrade head` — but it was previously only present transitively through
  `alembic`'s own dependency graph, unpinned. Added explicitly to `requirements.txt`,
  pinned to the version actually installed (`2.0.49`).

---

## P2 — backlog

- **No image registry / no git tags yet.** `docker-compose.prod.yml` still uses `build:
  .`; `git tag` returns zero tags even after this session's commits. Rollback today means
  a full rebuild (per `DEPLOYMENT.md` §2's rollback runbook), not an instant image swap.
  The gate checklist already asks for a tag per deploy — actually doing it, and ideally
  pushing built images to a registry, would make an incident-time rollback faster.
- **`/healthz` degradation has no automated remediation.**
  [server.py:187-200](voice_transcriber/server.py#L187-L200) correctly 503s when
  `db.ping()` fails, and the Compose healthcheck marks `web` unhealthy — but `restart:
  unless-stopped` triggers on container *exit*, not failed healthcheck, so a sustained DB
  outage leaves `web` running and serving 503s rather than being cycled or alerting.
  nginx doesn't consult container health either — it proxies to `web:8000` regardless of
  healthcheck status, the same as Caddy did before it. This is what the external
  `/healthz` monitoring in `DEPLOYMENT.md` §3 is for; it needs to actually exist
  operationally.
- **`@app.on_event` is deprecated but functional.** Confirmed via the exact
  `DeprecationWarning` FastAPI still emits at test time; `fastapi==0.141.1` still supports
  it. Same-effort, no-risk cleanup whenever convenient, not launch-relevant.

---

## Notes

- **Ownership/authorization checks are consistent and correctly fail closed to 404.**
  Every recording route goes through `_authorize_recording()`
  ([routes_api.py:325-332](voice_transcriber/routes_api.py#L325-L332)), 404s (not 403s) on
  a mismatched `user_id`. `rec_id` is only ever an exact-match DB lookup key, never
  path-concatenated. Every `/api/admin/*` route requires `Depends(auth.current_admin)`
  server-side; the frontend's `RequireAuth adminOnly` is UX convenience, not the
  enforcement mechanism. Unchanged this pass — no route/auth logic was touched.
- **Boot-time secret guards genuinely run before the app can serve traffic.**
  `config.py`'s `DATABASE_URL`/`SONIOX_API_KEY`/`ALLOW_TEST_HOOKS` checks and `auth.py`'s
  `JWT_SECRET` check are module-level, raising at **import time** — architecturally
  earlier than `@app.on_event("startup")`. `ADMIN_PASSWORD`'s guard is correctly scoped to
  first-boot only (`db.count_admins() == 0`). Unchanged this pass.
- **Migrations auto-apply on every boot with no advisory lock — a non-issue for this
  specific deployment.** Only matters with concurrent multi-instance startup;
  `--workers 1` and the single-container topology mean that can't happen as shipped.
  Unchanged this pass; still exactly two migration files, both with real (non-no-op)
  `downgrade()` bodies.
- **No secret leakage found in logging paths.** Re-grepped every `log.*` call across
  `voice_transcriber/` this pass — only guard messages naming *which* variable is
  missing/weak, never the value. `translate.py`'s `DEBUG_TOKENS` gate still defaults off.
- **No committed secrets found anywhere in the tracked tree**, beyond the
  already-documented, already-public dev Postgres default (`zenoscribe`/`zenoscribe`).
  Checked for PEM keys, AWS/GitHub/Slack token formats, and generic
  `key/secret/token/password = <literal>` assignments.
- **No TODO/FIXME/XXX/HACK markers anywhere in the tracked tree.**
- **`E2E_Review.md`'s open items are backlog, not blockers** — multi-instance scaling
  gaps (S3 storage, shared `SERVER_BOOT_ID`, in-memory rate limiter), manual secret
  rotation, and no real-device mobile testing are all explicitly deferred scope for a
  single-VM launch, not oversights.

---

## Verified working

- Full fast backend suite: `python -m pytest -q` → **81 passed, 21 deselected**, re-run
  this pass.
- `python -m flake8 voice_transcriber scripts --max-line-length=120` → clean, re-run this
  pass.
- Frontend build: `npm --prefix frontend run build` → succeeds, `login.js` (this
  session's CSP fix) lands in `dist/` correctly.
- Frontend suite: `npm --prefix frontend test` → **212 passed (212)**, re-run this pass.
- `docker-compose.prod.yml` parses as valid YAML with the expected four services (`db`,
  `web`, `nginx`, `certbot`) and four volumes.
- `frontend/nginx.conf` has balanced braces (14 open / 14 close) — a syntax sanity check
  only, not a substitute for `nginx -t` (see P1-B).
- `uvicorn/middleware/proxy_headers.py`'s trust behavior confirmed by reading the
  installed package source directly, not assumed (see P1-A).
- Recording ownership checks, admin-route gating, and no-path-traversal-via-`rec_id`
  re-traced through `routes_api.py`.
- No secret values (only variable *names*) in any `log.*` call across the backend.
- `.dockerignore` still correctly excludes `.env*` and `voice_transcriber/recordings/`;
  CI's `docker-build` job independently re-verifies no `.env` lands in the built image on
  every push.

## Unverified / needs access

- **A live `docker-compose.prod.yml` run, end to end.** Still no `docker` CLI in this
  environment. This is now P1-B above rather than a background item — the new edge stack
  specifically needs this, not just a nice-to-have re-confirmation of already-working
  infrastructure.
- **Actual VM disk size and expected concurrent-usage volume** for P1-C — depends on the
  target VM, not knowable from the repo.
- **Whether any external monitoring is actually watching `/healthz`, disk usage, and
  certificate expiry today.** `DEPLOYMENT.md` asks the deploy team to set these up;
  nothing in the repo can confirm they exist.
- **Mobile real-device behavior** — unchanged, still unverified on real hardware.

---

## Pre-deploy checklist

```bash
# 1. Fresh clone, confirm nothing depends on local/dev state
git clone <repo-url> zenoscribe-deploy && cd zenoscribe-deploy
cp .env.production.example .env.production
# fill in: POSTGRES_PASSWORD, SONIOX_API_KEY (a fresh production key, not dev's),
#          JWT_SECRET (python -c "import secrets; print(secrets.token_urlsafe(48))"),
#          ADMIN_PASSWORD (strong, >=8 chars), SERVER_BOOT_ID (pin it, or accept
#          that every restart logs everyone out - decide this deliberately),
#          DOMAIN, CERTBOT_EMAIL

# 2. Hand-edit the real domain into frontend/nginx.conf (server_name + ssl_certificate
#    paths) - same manual pattern the old Caddyfile used, see that file's header comment

# 3. Prove the production guards actually fire (DEPLOYMENT.md's own gate item)
#    Temporarily blank JWT_SECRET in .env.production and confirm the container
#    refuses to start, then restore it.

# 4. One-time TLS bootstrap (P1-B - this is the step that's never been run end to end)
./scripts/init-letsencrypt.sh

# 5. Build and bring up the rest of the stack
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build

# 6. Confirm the image contents match expectations
docker run --rm $(docker compose -f docker-compose.prod.yml images -q web) ls -a /app
#   -> only .env.example / .env.production.example, no real .env

# 7. Confirm port 8000 is not reachable from the host
curl -m 3 http://127.0.0.1:8000/healthz   # should fail to connect (only nginx can reach it)

# 8. Confirm the certificate is real Let's Encrypt, not the bootstrap dummy self-signed one
openssl s_client -connect $DOMAIN:443 -servername $DOMAIN </dev/null 2>/dev/null | openssl x509 -noout -issuer

# 9. Set up disk-usage alerting on the VM NOW (P1-C) - before real traffic, not after
# 10. Set up certificate-expiry alerting on the VM NOW (P1-D)
# 11. Set up external monitoring against GET /healthz (DEPLOYMENT.md §3)

# 12. Full test suite green on the exact deployed commit
python -m flake8 voice_transcriber scripts --max-line-length=120
python -m pytest -q
npm --prefix frontend run build
npm --prefix frontend test

# 13. Tag the release
git tag deploy-$(date +%Y%m%d) && git push --tags   # only if the user wants this pushed

# --- Post-deploy smoke test (over the real HTTPS domain, not localhost) ---
# a. Log in as the seeded admin; confirm the login page loads over TLS with the
#    security headers present:
curl -sI https://$DOMAIN/ | grep -Ei 'strict-transport|x-frame|x-content-type|content-security'
# b. Create one real user via the admin console.
# c. As that user: start a live recording, speak a sentence, stop it, confirm the
#    transcript appears in "My recordings" and the audio file downloads.
# d. As that user: try /translate one-way for a few seconds; confirm captions and
#    (if enabled) spoken TTS playback work.
# e. As that user: upload a short audio file via /upload; confirm it returns turns
#    and shows up in "My recordings" tagged source=upload.
# f. Negative auth check: as a second user, try GET /api/recordings/{first user's
#    recording id}/audio - must be 404, not the file.
# g. GET https://$DOMAIN/healthz -> {"status":"ok","database":"ok"}
```

---

## If you scale beyond one container

Kept separate from the verdict above per this audit's scope — already accurately
documented in `E2E_Review.md`'s "Open items" §1 and not launch risks for the single-VM/
`--workers 1`/single-container deployment this repo actually ships:

- **Recordings storage** is a local named Docker volume; a second replica can't see the
  first's files. Needs S3-compatible object storage before any horizontal scale.
- **`SERVER_BOOT_ID`** is generated per-process; multiple instances would each mint their
  own, so a session would randomly 401 depending on which instance handled a given
  request. Needs a shared value or a shared session-validity store.
- **`rate_limit.py`** counters are an in-memory `dict` per process — multiple instances
  multiply a user's effective quota by instance count rather than enforcing one global
  limit. Needs Redis or equivalent shared state to stay precise at scale.
- **`--workers 1` is load-bearing**, not just a default — raising it without addressing
  `SERVER_BOOT_ID` and concurrent-migration-on-startup first would reintroduce both
  problems inside a single container, before even reaching multi-container concerns.
