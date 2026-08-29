# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Batch uploads over ~60s returned a 504 to the user while the backend went on
  to succeed. `frontend/nginx.conf`'s `location /api/` set no proxy timeouts, so
  it inherited nginx's default `proxy_read_timeout` of 60s - but
  `POST /api/transcribe` and `/api/transcribe/translate` await Soniox
  *synchronously inside the request* (`routers/uploads.py`), with
  `soniox_client.BATCH_POLL_TIMEOUT` set to 600s. Every upload past a minute was
  cut at the edge while the worker thread kept running, finished, and called
  `_persist_upload_recording` - so the recording appeared in My Recordings after
  the user had been told the upload failed, and the natural response (re-upload)
  paid Soniox twice for one file. `location /api/` now sets
  `proxy_read_timeout`/`proxy_send_timeout` to 600s, derived from the worst-case
  request rather than picked: 230s of Soniox hops in series (upload, job
  creation, the poll loop, transcript fetch, cleanup) plus one full queued round
  behind `_UPLOAD_EXECUTOR`'s three workers, which `run_in_executor` fills with
  no timeout of its own. Same reasoning `client_max_body_size` already used - the
  app's own limit, which carries a message, must be what rejects a request,
  never the edge.
- `BATCH_POLL_TIMEOUT` lowered from 600s to 150s. It is synchronous request
  wall-clock, not background work, so ten minutes was never a real setting -
  only one nothing had reached. It stays a module constant rather than joining
  its three env-configurable siblings on purpose: it is now half of a two-file
  invariant with `nginx.conf`, and an env var would let an operator break it in
  production, at runtime, where no test can see it.

### Added

- `voice_transcriber/tests/test_nginx_upload_timeout.py` parses
  `proxy_read_timeout` back out of `frontend/nginx.conf`'s `/api/` block and
  re-derives the required headroom from the `soniox_client` timeouts and
  `_UPLOAD_EXECUTOR`'s worker count. The two numbers are one decision written in
  two files and two languages with nothing else connecting them; without this,
  the next person to tune either side silently restores the bug. Pure file
  parsing - no Docker, nginx, or network - so it runs in the fast suite.
- `UploadPanel` now shows an indeterminate progress state with a live elapsed
  count (reusing `useElapsedTimer`) and tells the user long recordings take a
  few minutes and to keep the tab open. Previously a two-minute wait looked
  identical to a hang behind a static "Transcribing..." label. Real byte-level
  progress is deliberately not attempted: `fetch()` cannot report upload
  progress, so it would mean replacing `fetchBaseQuery` with an XHR base query
  for this one endpoint.

## [1.3.6] - 2026-08-28

### Added

- `DEPLOYMENT.md` gained an explicit pre-deploy/deploy/post-deploy spine.
  §2 is now 2.1 (prerequisites: VM, DNS resolving before the TLS bootstrap,
  firewall, secret generation, `.env.production`, the `nginx.conf` domain
  edit, deploying a gate-green tag), 2.2 (the first deploy, step by step),
  2.3 (verification: `ps`/`/healthz`/logs, and how to read each failure),
  2.4 (the monitoring and backup jobs to wire up immediately), and 2.5
  (deploying a new release). The actual deploy command previously appeared
  only inside a §7 checkbox, and there was no roll-forward procedure at all -
  only rollback.
- `APP_VERSION`/`GIT_SHA` documented as build args in `DEPLOYMENT.md`.
  `docker-compose.prod.yml` has consumed them since 1.2.x, but nothing told
  the deploy team to export them, so a manual VM build stamped every image
  `dev`/`unknown` and `GET /healthz` could not identify the running build.

### Changed

- `DEPLOYMENT.md` §7's gate trimmed from ten items to seven, with a preamble
  listing what `release-gate.yml` already proves on every PR into `main`,
  push to `main`, and version tag. Dropped: the manual check for a leaked
  `.env` in the built image (`docker-build` greps for it), the
  `STORAGE_BACKEND`/`REDIS_URL` guard checks (`prod-config-guardrails`
  covers all six of `config.py`'s guards), and the manual re-run of the full
  test suite. The `JWT_SECRET`/`SERVER_BOOT_ID` check stays and now covers
  both - those guards live in `auth.py` and are outside CI's guardrail
  matrix.
- `docs/audits/DEPLOYMENT_READINESS_AUDIT.md`'s pre-deploy checklist no
  longer duplicates the deploy procedure; it defers to `DEPLOYMENT.md` and
  keeps only the audit-specific checks (port 8000 unreachable from the host,
  security headers over the real domain) and the smoke test.

### Fixed

- Four broken cross-references in `DEPLOYMENT.md`: the `docker-build` job
  cited as living in `ci.yml` (it is in `release-gate.yml`), a pointer to a
  README section that does not exist, a `/healthz` response shape attributed
  to the README (now stated inline), and a "§3 below" that is above.
- Stale references in `docs/audits/DEPLOYMENT_READINESS_AUDIT.md`: six
  `file:line` citations into `routes_api.py`/`server.py`/`auth.py`/
  `transcribe.py` that no longer pointed at the code they described (the
  route handlers moved into `voice_transcriber/routers/` in 1.2.7), two
  section pointers into `DEPLOYMENT.md`, the claim that the repository has
  no git tags (there are 17), and the `docker-build` trigger description.

## [1.3.5] - 2026-08-28

### Added

- Retroactive changelog entry for 1.3.4, which shipped the changelog backfill
  itself and so was never documented in it.
- GitHub Releases published for every tag from 1.2.1 onward; only 1.0.0,
  1.1.0 and 1.2.0 had Release objects before, so the repository's "Latest
  release" still advertised 1.2.0.

### Changed

- Convention going forward: a version's changelog entry is written in the
  same PR that gets tagged, not afterwards - which is what created the 1.3.4
  gap.

## [1.3.4] - 2026-08-28

### Added

- Changelog entries backfilled for 1.1.0 through 1.3.3. Fourteen releases had
  shipped with only 1.0.0 documented.

### Fixed

- Fifteen references naming `routes_api.py` for code that moved into
  `voice_transcriber/routers/` in 1.2.7, across `DEPLOYMENT.md`,
  `docs/architecture.md`, `db.py`, `rate_limit.py`, `server.py`,
  `storage/base.py`, `storage/local.py`, `storage/minio_backend.py`,
  `scripts/reconcile_recordings.py` and three test modules.

### Removed

- `black==26.5.1` from `requirements-dev.txt`. Nothing ran it - not CI, not a
  script, not a hook. Adopting it would reformat 51 of 63 files and require
  reconciling its 88-column default with the flake8 gate's 120, so it is a
  decision rather than a cleanup; the reasoning is recorded in the file.

## [1.3.3] - 2026-08-27

### Changed

- `docs/frontend.md`'s linting section rewritten as an optional guide.
  Verified that ESLint itself is *not* blocked by TypeScript 7 - only
  `typescript-eslint` is - and that `eslint-plugin-react-hooks` runs today
  via Babel's parser. Includes install steps, config, npm script and CI
  step. Nothing installed; the option is documented, not taken.

## [1.3.2] - 2026-08-27

### Fixed

- Replaced the deprecated `HTTP_413_REQUEST_ENTITY_TOO_LARGE` with
  `HTTP_413_CONTENT_TOO_LARGE` at four call sites in `routers/uploads.py`.
  Both resolve to 413, so responses are unchanged. This was the last warning
  in the test suite, which now passes under `-W error`.

## [1.3.1] - 2026-08-27

### Fixed

- `.env.example` and `.env.production.example` referenced the audit
  documents as repo-root files; they moved to `docs/audits/` in 1.2.6. Four
  references corrected (`SCALABILITY_DESIGN.md` §2, and
  `SCALABILITY_AUDIT.md` findings F1/F2/F3 behind `STORAGE_BACKEND`,
  `REDIS_URL` and `SERVER_BOOT_ID`).

## [1.3.0] - 2026-08-27

### Added

- `LAST_SEEN_DEBOUNCE_SEC` (default `60`): how long a process reuses its own
  `users.last_seen` write for a user before writing again. `0` restores the
  previous write-on-every-request behaviour.
- `voice_transcriber/tests/test_presence.py` - presence had no test coverage
  before this.

### Changed

- Presence writes are debounced instead of firing on every authenticated
  request. Measured: 50 authenticated requests now issue 1 database write
  instead of 50. Two layers - an in-memory gate checked before any thread
  hop or connection checkout, and a conditional `WHERE` so writes that do get
  issued match zero rows when `last_seen` is already fresh.
- `users.last_seen` is now accurate to within the debounce window rather
  than exact to the request. The admin console's online/offline indicator is
  unaffected.

## [1.2.8] - 2026-08-27

### Fixed

- `docs/frontend.md` claimed Prettier was "not enforced in CI yet". It has
  been enforced since `format:check` landed in `ci.yml`'s `frontend-unit`
  job, which feeds the `Dev checks passed` aggregator.
- The ESLint deferral note pointed at downgrading to TypeScript 5.9.x;
  refreshed with the verified blocker (typescript-eslint 8.68.0 requires
  `typescript >=4.8.4 <6.1.0`).

## [1.2.7] - 2026-08-27

### Changed

- `routes_api.py` split from 638 lines into domain routers under
  `voice_transcriber/routers/`: `auth.py` (2 endpoints), `admin.py` (5),
  `test_hooks.py` (1), `recordings.py` (4), `uploads.py` (2).
  `routes_api.py` remains as a 42-line aggregator that re-exports the names
  tests and other modules already depend on.
- No behaviour change: the route table (methods, paths, handler names and
  registration order) and the generated OpenAPI schema are both identical to
  before the split, and every test passed unmodified.

## [1.2.6] - 2026-08-27

### Changed

- `README.md` trimmed from 898 to ~260 lines; repo root reduced from nine
  markdown files to four (README, CONTRIBUTING, DEPLOYMENT, CHANGELOG).
- Five audit/design writeups moved to `docs/audits/`, with a README there
  framing them as point-in-time snapshots rather than current behaviour.
- Frontend architecture moved to `docs/frontend.md`; data/storage, sessions
  and tokens, turn-detection tuning and batch transcription moved to
  `docs/architecture.md`.
- `DEPLOYMENT.md` §1 gained two subsections carrying content that had no
  home elsewhere: how `ENV` and `.env.production` reach the process, and the
  single-combined-container path.

### Fixed

- A stale README paragraph describing `ci.yml` as having six jobs including
  Playwright, Trivy and the dependency audit; those moved to
  `release-gate.yml` when the CI tiers were introduced.

## [1.2.5] - 2026-08-27

### Changed

- `server.py`'s deprecated `@app.on_event("startup"/"shutdown")` pair
  replaced with a single `lifespan` async context manager. Startup and
  shutdown behaviour, including the graceful session drain, is unchanged.

## [1.2.4] - 2026-08-27

### Removed

- `voice_transcriber/code_reviews/` - three development working-note files
  versioned inside the shipped application package. `.dockerignore` already
  excluded them, so the built image is unchanged; the now-dead entry was
  dropped with them.

## [1.2.3] - 2026-08-27

### Added

- `docs/github-repo-settings.md` §2a documenting that Dependabot-triggered
  workflow runs read from a separate secret store, so `CI_POSTGRES_PASSWORD`
  must also be set via `gh secret set --app dependabot`. Without it every
  Dependabot PR fails at ~18s when the Postgres service container refuses to
  initialize.

## [1.2.2] - 2026-08-27

### Fixed

- `docs/github-repo-settings.md` §4 documented `required_linear_history=true`
  for `main`; the live value is `false` and deliberately so, since the
  release flow merges `dev` into `main` without squashing. Applying the doc
  verbatim would have blocked the merge button on every release PR.

## [1.2.1] - 2026-08-27

### Fixed

- Rate limiting falls back to in-memory counters outside production instead
  of failing closed when Redis is unreachable.
- The upload page is its own scroll container.

## [1.2.0] - 2026-08-27

### Added

- Coverage gates for the backend pytest and frontend Vitest suites.
- Prettier `format:check` gated on every PR.

### Changed

- Dependabot auto-rebase enabled so queued PRs don't stall behind each
  other; Node 25.x bumps ignored until 26 LTS.
- Dependency bumps: psycopg 3.3.4, scipy 1.18.1, python-dotenv 1.2.3,
  SQLAlchemy 2.0.52, nginx 1.31-alpine, Vite 8.2.2, and the GitHub Actions
  checkout/setup-node/setup-python majors.

## [1.1.0] - 2026-08-26

### Added

- Version stamping of the built image via `APP_VERSION`/`GIT_SHA`, surfaced
  on `/healthz`.
- Repository governance files: `LICENSE`, PR template, `CODEOWNERS`,
  `CHANGELOG.md`.

### Changed

- Tier 1 CI always runs on PRs into `dev`.
- `.claude/` untracked and ignored.

## [1.0.0] - 2026-08-26

### Added

- nginx TLS edge for the production deployment
- Redis-backed rate limiting
- MinIO object storage for recordings
- `dev`/`main` branch model: `dev` as the default/integration branch, `main`
  as the production branch, promoted via a release PR + tag
- Tiered CI: `ci.yml` (Tier 1-2, aggregator "Dev checks passed"),
  `release-gate.yml` (Tier 3, aggregator "Production gate passed"),
  `nightly-e2e-dev.yml`, `scheduled-audit.yml`
- `CONTRIBUTING.md` documenting the branch model and CI tiers
- `docs/github-repo-settings.md` documenting non-tracked repository
  configuration (default branch, required secrets/variables, branch
  protection)

[1.3.6]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.3.6
[1.3.5]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.3.5
[1.3.4]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.3.4
[1.3.3]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.3.3
[1.3.2]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.3.2
[1.3.1]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.3.1
[1.3.0]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.3.0
[1.2.8]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.2.8
[1.2.7]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.2.7
[1.2.6]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.2.6
[1.2.5]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.2.5
[1.2.4]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.2.4
[1.2.3]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.2.3
[1.2.2]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.2.2
[1.2.1]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.2.1
[1.2.0]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.2.0
[1.1.0]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.1.0
[1.0.0]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.0.0
