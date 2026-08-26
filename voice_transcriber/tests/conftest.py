"""Shared fixtures for the voice_transcriber test suite.

Isolation strategy: every test that touches the database gets a private
Postgres *schema* on the shared dev/CI database (Postgres has no equivalent
of SQLite's "point at a fresh file" trick). A unique `test_<uuid>` schema is
created, Alembic migrations are run against it via a search_path-scoped
DSN, and it's dropped again on teardown - so tests never see each other's
rows and never touch a real `public` schema's data. `config.DATABASE_URL` is
read fresh by db.py on every pool creation (not captured at import time),
which is what makes monkeypatching it here sufficient on its own. The
recordings directory is isolated the same way it always was, via
`config.RECORDINGS` monkeypatching.
"""
import io
import os
import socket
import subprocess
import sys
import time
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import fakeredis
import psycopg
import pytest
import requests
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from voice_transcriber import auth, config, db, rate_limit, redis_client, soniox_client  # noqa: E402
from voice_transcriber.server import app  # noqa: E402


def _scoped_dsn(base_url: str, schema: str) -> str:
    """base_url with a libpq `options=-c search_path=<schema>` param added,
    so any connection made with it (in-process or a subprocess) resolves
    unqualified table names into that schema alone. Deliberately excludes
    `public` - the initial migration references the `citext` extension type
    fully-qualified (public.citext) for exactly this reason, so that an
    unqualified `alembic_version` or `users` lookup can never fall through
    to (or silently write into) the real `public` schema when a test schema
    doesn't have its own copy yet."""
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query))
    query["options"] = f"-c search_path={schema}"
    new_query = urlencode(query, quote_via=quote)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def _create_test_schema(base_url: str) -> str:
    schema = f"test_{uuid.uuid4().hex}"
    with psycopg.connect(base_url, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    return schema


def _drop_test_schema(base_url: str, schema: str):
    with psycopg.connect(base_url, autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.fixture
def isolated_db(monkeypatch):
    base_url = config.DATABASE_URL
    schema = _create_test_schema(base_url)
    try:
        monkeypatch.setattr(config, "DATABASE_URL", _scoped_dsn(base_url, schema))
        monkeypatch.setattr(db, "_pool", None)
        db.init()
        yield db
    finally:
        if db._pool is not None:
            db._pool.close()
            db._pool = None
        _drop_test_schema(base_url, schema)


@pytest.fixture
def isolated_recordings(tmp_path, monkeypatch):
    recordings_dir = tmp_path / "recordings"
    recordings_dir.mkdir()
    monkeypatch.setattr(config, "RECORDINGS", recordings_dir)
    yield recordings_dir


@pytest.fixture
def isolated_redis(monkeypatch):
    """A fakeredis instance standing in for the real REDIS_URL - fakeredis
    implements Redis's Lua/EVAL scripting (verified directly: it correctly
    runs rate_limit.py's actual sliding-window script, not just simple
    GET/SET), so this is real coverage of rate_limit.py's logic, not a stub
    that merely avoids errors. No real Redis server is available in this
    dev/CI environment - see SCALABILITY_AUDIT.md's environment note."""
    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(redis_client, "_client", fake)
    monkeypatch.setattr(rate_limit, "_script", None)
    yield fake
    fake.flushall()


@pytest.fixture
def client(isolated_db, isolated_recordings, isolated_redis, monkeypatch):
    """TestClient for the shared app, isolated from the real dev DB/recordings.

    ADMIN_USERNAME/ADMIN_PASSWORD are pinned to fixed test-only values before
    startup fires, so the admin auth.ensure_seed_admin() creates is
    deterministic and independent of whatever the developer's real .env
    contains - tests that need an admin still create their own via
    make_user() rather than relying on this seeded one. ALLOW_TEST_HOOKS is
    likewise forced off here so hook-gating tests don't depend on whatever
    the developer's real .env happens to set; tests that need hooks enabled
    monkeypatch it back to True themselves (see test_internal_test_hook.py).

    rate_limit's counters are isolated per test via the isolated_redis
    fixture (a fresh fakeredis instance each time) - this fixture's `app` is
    the one module-level FastAPI instance imported at the top of this file
    and reused across every fast test, so without that isolation,
    rate_limit's counters (keyed by user id / IP, both of which repeat a lot
    across this suite - many tests share the "testclient" fake IP) would
    accumulate across the whole run instead of resetting per test.
    """
    monkeypatch.setenv("ADMIN_USERNAME", "seed-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "Seed-Admin-Password-123")
    monkeypatch.setattr(config, "ALLOW_TEST_HOOKS", False)
    rate_limit.reset_all()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_user(isolated_db):
    """Factory: make_user(username, password, role="user", **kw) -> user_id.

    Creates the user directly via db.create_user(), no HTTP round-trip. No
    manual cleanup needed - the isolated per-test DB is discarded with tmp_path.
    """
    def _make(username, password, role="user", full_name="", email=""):
        return db.create_user(
            username=username,
            password_hash=auth.hash_password(password),
            full_name=full_name or username,
            email=email,
            role=role,
        )
    return _make


@pytest.fixture
def make_wav():
    """Factory returning a small valid WAV (1s of 16kHz mono silence).

    make_wav() -> io.BytesIO, ready for TestClient's files={...}.
    make_wav(path=some_path) -> writes the same WAV to disk and returns the
    Path, for tests (e.g. the Playwright E2E test) that need a real file.
    """
    def _make(path=None, num_frames=16000):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * num_frames)
        if path is not None:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(buf.getvalue())
            return path
        buf.seek(0)
        return buf
    return _make


@pytest.fixture(autouse=True)
def reset_soniox_fake_mode():
    """Belt-and-braces: most tests monkeypatch routes_api.sx.transcribe_file
    directly and never touch this global, but guard against test-order
    dependence for anything that does exercise the real test-hook path.
    """
    soniox_client.set_test_fake_mode(None)
    yield
    soniox_client.set_test_fake_mode(None)


@dataclass
class LiveServer:
    base_url: str
    hook_secret: str
    admin_username: str
    admin_password: str


@pytest.fixture
def live_server(tmp_path, monkeypatch):
    """Launch a real uvicorn subprocess on an ephemeral port with test hooks
    enabled, for the one true black-box (Playwright) integration test.

    The admin user is created in the DB *before* the subprocess is launched,
    against a schema-scoped DATABASE_URL that's also passed to the subprocess
    via its env (a separate process can't see this process's monkeypatches),
    so there's no race with the subprocess's own startup event, which just
    finds the schema/admin already present (db.init()/ensure_seed_admin()
    are both idempotent).

    PYTHONPATH is set explicitly to the repo root since the subprocess's cwd
    is tmp_path, not the repo root, so `import voice_transcriber` inside it
    needs help finding the package.
    """
    base_url_db = config.DATABASE_URL
    schema = _create_test_schema(base_url_db)
    scoped_url = _scoped_dsn(base_url_db, schema)
    try:
        monkeypatch.setattr(config, "DATABASE_URL", scoped_url)
        monkeypatch.setattr(db, "_pool", None)
        db.init()
        admin_username = "e2e_admin"
        admin_password = "E2EPass123!"
        db.create_user(
            admin_username, auth.hash_password(admin_password),
            full_name="E2E Admin", role="admin",
        )
        if db._pool is not None:
            db._pool.close()
            db._pool = None

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        hook_secret = "e2e-secret"
        env = os.environ.copy()
        env["DATABASE_URL"] = scoped_url
        env["ALLOW_TEST_HOOKS"] = "true"
        env["TEST_HOOK_SECRET"] = hook_secret
        env["PYTHONPATH"] = str(REPO_ROOT)
        # Force an invalid Soniox key regardless of what the developer's own
        # .env has configured (os.environ.copy() would otherwise inherit a real
        # one). No `integration`-marked test should depend on - or spend quota
        # against - the real Soniox API; that's what the separately-gated
        # `real_network` marker (RUN_REAL_SONIOX_TESTS=true) is for. Tests that
        # need Soniox behavior without a real key use the ALLOW_TEST_HOOKS fake
        # mode above instead.
        env["SONIOX_API_KEY"] = "test-invalid-soniox-key"

        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "voice_transcriber.server:app",
             "--host", "127.0.0.1", "--port", str(port)],
            cwd=tmp_path, env=env,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            for _ in range(60):
                try:
                    if requests.get(base_url + "/", timeout=2).status_code == 200:
                        break
                except requests.RequestException:
                    pass
                time.sleep(0.5)
            else:
                proc.kill()
                pytest.fail("live_server did not become healthy in time")
            yield LiveServer(base_url, hook_secret, admin_username, admin_password)
        finally:
            proc.kill()
            proc.wait(timeout=10)
    finally:
        _drop_test_schema(base_url_db, schema)


def seed_auth_script(token, user):
    """JS to seed sessionStorage before a page's own script runs, via
    BrowserContext.add_init_script - the same auth handoff every
    test_e2e_playwright_*.py file needs.
    """
    import json as _json

    return (
        f"sessionStorage.setItem('token', {_json.dumps(token)}); "
        f"sessionStorage.setItem('user', {_json.dumps(_json.dumps(user))});"
    )


def best_effort_unlink(paths, attempts=40, delay_sec=0.3):
    """Retries deletion for a bit, since a live_server-backed test may be
    racing the server's own async cleanup of a file it just wrote (e.g. the
    recorder's WAV writer) - on Windows an open file handle blocks deletion
    outright (PermissionError), so an immediate unlink can fire before the
    server finishes tearing a session down. Best-effort: never fails the
    test, just tries hard not to leave debris in the real (non-isolated)
    recordings/ dir (config.RECORDINGS isn't overridden for live_server,
    since a separate subprocess can't see this process's monkeypatches).
    """
    remaining = set(paths)
    for _ in range(attempts):
        if not remaining:
            return
        still_locked = set()
        for f in remaining:
            try:
                f.unlink(missing_ok=True)
            except PermissionError:
                still_locked.add(f)
        remaining = still_locked
        if remaining:
            time.sleep(delay_sec)
