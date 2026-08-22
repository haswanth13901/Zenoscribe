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
RECORDINGS = BASE_DIR / "recordings"
RECORDINGS.mkdir(exist_ok=True)

# Postgres connection string, e.g. postgresql://user:pass@host:port/dbname.
# Production requires an explicit value; the dev default below matches the
# `db` service in docker-compose.yml and must never be used in production.
_database_url_env = os.environ.get('DATABASE_URL')
if PRODUCTION and not _database_url_env:
    raise RuntimeError("Missing DATABASE_URL in production environment")
DATABASE_URL = _database_url_env or 'postgresql://zenoscribe:zenoscribe@localhost:5432/zenoscribe'

# Soniox API key. A missing/typo'd key still boots cleanly and passes a
# health check if this isn't checked here - it only surfaces as an uncaught
# KeyError (see soniox_client.get_api_key()) the first time a user hits
# record, which looks like a generic 500 with no clue what's wrong.
if PRODUCTION and not os.environ.get('SONIOX_API_KEY'):
    raise RuntimeError("Missing SONIOX_API_KEY in production environment")

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

# Maximum batch upload size for /api/transcribe.
# This is enforced on Content-Length when available and while streaming.
MAX_UPLOAD_MB = 20
MAX_UPLOAD_SIZE = MAX_UPLOAD_MB * 1024 * 1024

# These only affect the engine in transcribe.py. Adjust them there-and-only
# there when tuning turn detection; nothing in the auth layer reads them.

# Flush a turn this many seconds after the last finalized token arrives.
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
