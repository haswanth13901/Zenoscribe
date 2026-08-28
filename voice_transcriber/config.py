"""Shared settings.

Kept separate so the auth layer and the transcription engine can both read
paths without importing each other.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
REPO_ROOT = BASE_DIR.parent

# Which dotenv file to load: .env.<ENV> if present (e.g. .env.production),
# else the plain .env used for development/testing. ENV itself has to come
# from a real process env var (docker-compose `environment:`, systemd,
# platform secrets UI) - it can't live inside the file it's used to select.
# This must run before anything below reads os.environ, and config.py must
# be the first project module imported (it is - every other module imports
# config before touching env vars), so this is the single place env files
# get loaded from.
_env_name = os.environ.get('ENV', 'development').lower()
_env_specific_file = REPO_ROOT / f".env.{_env_name}"
ENV_FILE = _env_specific_file if _env_specific_file.exists() else REPO_ROOT / ".env"
load_dotenv(ENV_FILE)

# Environment mode: 'development' (default), 'testing', or 'production'
ENV = os.environ.get('ENV', 'development').lower()
PRODUCTION = ENV == 'production'

# Set via the Dockerfile's ENV APP_VERSION/GIT_SHA (baked in at build time
# from --build-arg, see docker-compose.prod.yml and release-gate.yml) so a
# running container can report what image it actually is. Defaults below
# match the Dockerfile ARG defaults, for running outside a built image
# (bare `uvicorn` locally, tests).
APP_VERSION = os.environ.get('APP_VERSION', 'dev')
GIT_SHA = os.environ.get('GIT_SHA', 'unknown')
RECORDINGS = BASE_DIR / "recordings"
RECORDINGS.mkdir(exist_ok=True)


def live_scratch_dir() -> Path:
    """Scratch directory for a live session's WAV file while it's still
    being recorded (see transcribe.py/translate.py) - not a final
    destination. `wave` needs a real seekable file handle for incremental
    writes regardless of storage backend, so a live session always buffers
    locally first; the finished file is then handed to storage.upload() and
    removed from here. Resolved fresh against RECORDINGS on every call
    (never cached) so tests that monkeypatch config.RECORDINGS (see
    conftest.py's isolated_recordings fixture) get an isolated scratch dir
    too. The "_live" prefix can never collide with a real object key (those
    are always "users/...", see storage/base.py's recording_key())."""
    d = RECORDINGS / "_live"
    d.mkdir(exist_ok=True)
    return d


# Postgres connection string, e.g. postgresql://user:pass@host:port/dbname.
# Required in every mode - no hardcoded fallback. .env/.env.example set it
# explicitly for dev, .env.production.example for production, and CI sets
# it directly as a job env var (ci.yml) - there's no longer a scenario
# where this needs a value baked into source.
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise RuntimeError(
        "Missing DATABASE_URL - set it in .env (dev) or .env.production "
        "(production); see .env.example"
    )

# Soniox API key. A missing/typo'd key still boots cleanly and passes a
# health check if this isn't checked here - it only surfaces as an uncaught
# KeyError (see soniox_client.get_api_key()) the first time a user hits
# record, which looks like a generic 500 with no clue what's wrong.
if PRODUCTION and not os.environ.get('SONIOX_API_KEY'):
    raise RuntimeError("Missing SONIOX_API_KEY in production environment")

# Recording storage backend. 'local' (default) writes into RECORDINGS above -
# fine for a single container, but a second replica can't see another
# replica's files (see SCALABILITY_AUDIT.md finding F1). Production must use
# 'minio' instead, backed by a shared, self-hosted S3-compatible store -
# every replica then reads/writes the same objects regardless of which one
# handled the request. See voice_transcriber/storage/ for the abstraction.
STORAGE_BACKEND = os.environ.get('STORAGE_BACKEND', 'local').lower()
if PRODUCTION and STORAGE_BACKEND != 'minio':
    raise RuntimeError(
        "STORAGE_BACKEND must be 'minio' in production - 'local' storage is "
        "not shared across replicas and recordings would become invisible/"
        "lost depending on which replica handles a given request"
    )
MINIO_ENDPOINT = os.environ.get('MINIO_ENDPOINT', 'localhost:9000')
MINIO_ACCESS_KEY = os.environ.get('MINIO_ACCESS_KEY', '')
MINIO_SECRET_KEY = os.environ.get('MINIO_SECRET_KEY', '')
MINIO_BUCKET = os.environ.get('MINIO_BUCKET', 'zenoscribe-recordings')
MINIO_SECURE = os.environ.get('MINIO_SECURE', 'false').lower() in ('1', 'true', 'yes')
if PRODUCTION and STORAGE_BACKEND == 'minio' and not (MINIO_ACCESS_KEY and MINIO_SECRET_KEY):
    raise RuntimeError("Missing MINIO_ACCESS_KEY/MINIO_SECRET_KEY in production environment")

# Redis: shared rate-limit counters only, never durable business data (see
# SCALABILITY_DESIGN.md §3). Required in production because rate_limit.py's
# in-memory counters (the old default) don't stay accurate once more than
# one replica is handling traffic - see SCALABILITY_AUDIT.md finding F2.
REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'
if PRODUCTION and not os.environ.get('REDIS_URL'):
    raise RuntimeError("Missing REDIS_URL in production environment")

# Postgres connection pool size, per process/replica. Each replica opens its
# own pool (see db.py) - with N replicas, total connections against Postgres
# is roughly N * DB_POOL_MAX_SIZE, so this needs to shrink as replica count
# grows rather than staying at a single-instance-sized default. See
# DEPLOYMENT.md's sizing guidance.
DB_POOL_MAX_SIZE = int(os.environ.get('DB_POOL_MAX_SIZE', '10'))

# How long a process may reuse its own `users.last_seen` write for a given
# user before writing again. last_seen feeds exactly one thing - the admin
# console's online/offline indicator - so minute-level accuracy is ample,
# while the pre-debounce behaviour (a write on every authenticated request)
# cost one Postgres row version per request per active user. See db.py's
# should_touch_seen()/touch_seen() for the two layers this drives. Set to 0
# to restore a write on every request.
LAST_SEEN_DEBOUNCE_SEC = int(os.environ.get('LAST_SEEN_DEBOUNCE_SEC', '60'))

# frontend/ is the single source dir for all frontend files; the backend
# serves the Vite build output straight from frontend/dist/ (no separate
# static/ copy) - see the repo README's "Frontend" section.
FRONTEND_DIST_DIR = str(BASE_DIR.parent / "frontend" / "dist")

# Origin of the Vite dev server (see frontend/vite.config.ts), allowed
# through CORS only outside production - see server.py. The Vite proxy
# already keeps most browser requests same-origin, so this only matters for
# calls made straight to this app's own dev port instead of through the
# proxy (e.g. hitting :3000 directly while iterating).
DEV_FRONTEND_ORIGIN = os.environ.get('DEV_FRONTEND_ORIGIN', 'http://localhost:8000')

# Protect /api/login from brute-force attempts.
LOGIN_ATTEMPT_WINDOW_SEC = 300
LOGIN_ATTEMPT_LIMIT = 5

# Enforced on Content-Length when available, and while streaming.
MAX_UPLOAD_MB = 20
MAX_UPLOAD_SIZE = MAX_UPLOAD_MB * 1024 * 1024

# These only affect the engine in transcribe.py. Adjust them there-and-only
# there when tuning turn detection; nothing in the auth layer reads them.

# Must exceed a normal speaking pause, or turns split mid-sentence.
IDLE_FLUSH_SEC = 1.6

# Safety valve only - long enough that it rarely fires mid-thought.
MAX_TURN_CHARS = 400

# Punctuation alone doesn't end a turn; the speaker must also have paused.
SENTENCE_PAUSE_SEC = 0.5

# A turn is labeled by majority vote across its tokens, not by whichever
# speaker won the first word - that token is the one diarization is least
# sure about. A challenger must produce this many consecutive tokens to take
# over the turn. Raise to 3-4 if speakers still bleed into each other; lower
# to 1 to switch on the first disagreeing token.
VOTE_MARGIN = 2

# Language passed to Soniox. ["en"] locks English; add more for code-switching.
LANGUAGE_HINTS = ["en"]

DEBUG_SONIOX = False
# Log the raw speaker ID on each finalized token, to check whether Soniox is
# separating speakers at all.
DEBUG_SPEAKERS = False
# When true, translate.py will log token text in debug messages. Default
# is False; do not enable in production.
DEBUG_TOKENS = os.environ.get('DEBUG_TOKENS', 'false').lower() in ('1', 'true', 'yes')

# Allow tests to enable runtime-only admin endpoints that flip fake upstream
# behavior. This must be explicitly enabled in CI/dev; default is disabled.
ALLOW_TEST_HOOKS = os.environ.get('ALLOW_TEST_HOOKS', 'false').lower() in ('1', 'true', 'yes')
# Short shared secret required to call test hooks. Set in CI env when enabled.
TEST_HOOK_SECRET = os.environ.get('TEST_HOOK_SECRET')
RESTRICT_TEST_HOOK_TO_LOCALHOST = os.environ.get(
    'RESTRICT_TEST_HOOK_TO_LOCALHOST', 'true'
).lower() in ('1', 'true', 'yes')
if PRODUCTION and ALLOW_TEST_HOOKS:
    raise RuntimeError("ALLOW_TEST_HOOKS must not be enabled in production")
