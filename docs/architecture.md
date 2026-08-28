# Architecture reference

Where the data lives, how sessions are authenticated, and the knobs that
change transcription behavior. For the frontend, see
[frontend.md](frontend.md). For deploying any of it, see
[DEPLOYMENT.md](../DEPLOYMENT.md).

## Data & storage

- **Postgres** — users, recording metadata, presence. Connection configured via
  `DATABASE_URL` (see `.env.example`); for local dev this points at the `db`
  service in `docker-compose.yml`. Schema is managed with
  [Alembic](https://alembic.sqlalchemy.org/) migrations in `alembic/versions/`.
  **Migrations no longer apply automatically at app startup** (this changed
  once running more than one `web` replica became supported - concurrent,
  uncoordinated `alembic upgrade head` calls from several replicas starting
  at once could race). `db.init()` still runs them (idempotent, safe to call
  against an already-current database), but it's now an explicit step -
  `docker compose up` runs it for you via the one-shot `migrate` service; the
  app's own startup only *verifies* the schema matches what the code expects
  (`db.verify_schema_current()`) and refuses to serve otherwise. To manage
  migrations directly: `alembic upgrade head`, `alembic revision -m "..."`.
- **Redis** — rate-limit counters only (`rate_limit.py`), never durable data.
  Connection configured via `REDIS_URL` (see `.env.example`); for local dev
  this points at the `redis` service in `docker-compose.yml`. Losing Redis
  (restart, outage) never loses data - in production, rate limiting fails
  closed (503) until it's back, rather than silently allowing unlimited
  requests through. Outside production it instead falls back to
  process-local counters (accurate for a single dev process, and no use
  across replicas - which is why production doesn't do it), retrying Redis
  every 30s so shared counters resume on their own.
- **Recording storage** (`voice_transcriber/storage/`) — audio + transcript
  objects, addressed by an opaque key (`users/{user_id}/recordings/{id}.wav`
  etc.), never a raw filesystem path. Two backends:
  - `STORAGE_BACKEND=local` (dev/test default) — writes under
    `voice_transcriber/recordings/`, matching the key layout above.
  - `STORAGE_BACKEND=minio` (required in production) — a self-hosted
    S3-compatible object store, shared across every `web` replica (unlike a
    local directory, which only one replica could ever see). See
    `docker-compose.yml`'s opt-in `minio` service for local testing against a
    real MinIO instance, and [audits/SCALABILITY_DESIGN.md](audits/SCALABILITY_DESIGN.md) §2
    for the full design.
  Neither backend is ever served as static files; all access goes through
  authenticated, ownership-checked API routes (`_authorize_recording()` in
  `routers/recordings.py`), regardless of which backend answers the read.
- **`recordings.source`** — one of `transcribe` / `translate` / `upload`
  (`db.RECORDING_SOURCES`), recording which flow produced the row: a live
  transcription session, a live translate session, or a batch upload via
  `/api/transcribe` or `/api/transcribe/translate`. `GET /api/recordings`
  accepts an optional `source` filter alongside `user_id`/`date_from`/`date_to`.

`voice_transcriber/recordings/` is not committed to git (see `.gitignore`);
neither is `.env` (which holds `DATABASE_URL`/`REDIS_URL` and other secrets).

If stored recordings and the `recordings` table ever drift out of sync (e.g.
a partial failure mid-save, or a MinIO hiccup - the storage-upload steps in
transcribe.py/translate.py/routers/uploads.py are deliberately best-effort
so a
storage blip doesn't turn an otherwise-successful session into an error),
`scripts/reconcile_recordings.py` reports stored objects with no matching DB
row and DB rows pointing at missing objects. Works against either storage
backend. It's a dry-run report by default; pass `--delete` to also remove
orphaned objects (it never touches the database):

```bash
python scripts/reconcile_recordings.py            # report only
python scripts/reconcile_recordings.py --delete   # also delete orphan objects
```

## Sessions & tokens

- Login issues a JWT stored in the browser's `sessionStorage`, so closing the
  tab clears the session.
- Every protected page (`/app`, `/admin`, `/translate`, `/home`) checks
  `sessionStorage` for a token and user on load and redirects to `/login`
  immediately if either is missing — the page itself is not gated
  server-side, but every API call behind it is. A token that's present but
  stale/expired/invalid is only caught on the first authenticated request:
  the shared `api()`/fetch wrapper on each page (an RTK Query base query on
  `/home`) clears storage and redirects to `/login` on a `401`.
- Tokens expire after `TOKEN_HOURS` (default 8). Expiry is baked into each
  token, so a continuously running server does not keep anyone logged in past
  their window — the next request after expiry returns 401 and the page
  redirects to login. There is no automatic refresh; the user logs in again to
  get a fresh token.
- `JWT_SECRET` is a stable signing key, not something to rotate on a schedule.
  Set it once. Changing it invalidates every existing token at once — useful as
  a "log everyone out now" switch after a suspected leak, but not for routine
  operation.
- **Forcing re-login on a dev restart:** set `DEV_ROTATE_JWT_ON_RESTART=true` in
  a development `.env`. The secret is then regenerated on every startup, so
  restarting the dev server invalidates all tokens and sends every open page
  back to login. This flag is ignored in production, where the fixed
  `JWT_SECRET` is always used — but that alone does *not* mean deploys/restarts
  leave real users logged in. A separate mechanism does log everyone out on
  every restart by default: see `SERVER_BOOT_ID` below.
- **`SERVER_BOOT_ID` — required in production.** Independently of
  `JWT_SECRET`, every issued token is stamped with the boot ID of the server
  process that issued it (`auth.py`), and a token whose `boot` doesn't match
  the *currently running* process is rejected. In development, leaving it
  unset generates a fresh random boot ID per process start — so a plain
  `docker compose restart`, a crash loop, or a host reboot logs out every
  user even though `JWT_SECRET` never changed. In production the app now
  refuses to start without an explicit value: with more than one `web`
  replica, each generating its own random value would mean a token issued by
  one replica gets rejected by another (random 401s depending on which
  replica a load balancer routes a request to) - see
  [audits/SCALABILITY_AUDIT.md](audits/SCALABILITY_AUDIT.md) finding F3. Set
  `SERVER_BOOT_ID` to a fixed value
  in `.env.production` (see `.env.production.example`), the same value read
  by every replica, so restarts (and now, replicas) don't log anyone out.
  There is no way to revoke a single session early either way — see
  [DEPLOYMENT.md](../DEPLOYMENT.md)'s limitations section.

## Tuning turn detection

All in `config.py`:

| Constant | Meaning |
|---|---|
| `IDLE_FLUSH_SEC` | Close a turn after this much silence (default 1.6s) |
| `MAX_TURN_CHARS` | Hard cap so a turn stays readable (default 400) |
| `SENTENCE_PAUSE_SEC` | Pause required before punctuation ends a turn |
| `VOTE_MARGIN` | Consecutive tokens a new speaker needs to take over |
| `LANGUAGE_HINTS` | e.g. `["en"]`; add more for code-switching |
| `DEBUG_SONIOX` / `DEBUG_SPEAKERS` | Verbose logging toggles |

## Batch (non-live) transcription

`soniox_client.transcribe_file(path)` uploads a `.wav`/`.mp3` and returns merged
speaker turns using the async API, which has full-file context and is more
accurate than the live path. Exposed at `POST /api/transcribe` (authenticated),
and at `POST /api/transcribe/translate` for the same upload plus server-side
one-way translation.

A non-empty result from either endpoint is persisted the same way a live
session is — the uploaded audio is moved into `recordings/` (keeping its
original extension), a `.txt` transcript is written, and a `recordings` row is
added with `source="upload"` — so batch uploads show up in My/All Recordings
alongside live sessions. This is best-effort: a storage/DB failure here is
logged but does not turn an otherwise-successful transcription into an error
response for the caller.
