"""Alembic migration coverage for 884a0b02cf74 (recordings.source):
backfill correctness and upgrade/downgrade reversibility.

Uses the same schema-per-test isolation as conftest.py's isolated_db, but
drives Alembic to specific revisions directly (rather than always "head")
so it can insert pre-migration-shaped rows and assert on the backfill.
"""
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.rows import dict_row

from voice_transcriber import config, db
from voice_transcriber.tests.conftest import (
    _create_test_schema,
    _drop_test_schema,
    _scoped_dsn,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PRE_SOURCE_REVISION = "b9a728687f5b"
SOURCE_REVISION = "884a0b02cf74"


def _cfg() -> Config:
    return Config(str(REPO_ROOT / "alembic.ini"))


@pytest.fixture
def scoped_schema(monkeypatch):
    """Yields the isolated schema name, with config.DATABASE_URL pointed at
    it. Unlike isolated_db, does NOT run migrations - tests here control
    exactly which revision to migrate to."""
    base_url = config.DATABASE_URL
    schema = _create_test_schema(base_url)
    monkeypatch.setattr(config, "DATABASE_URL", _scoped_dsn(base_url, schema))
    try:
        yield schema
    finally:
        _drop_test_schema(base_url, schema)


def _connect():
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row, autocommit=True)


def _recordings_columns(schema):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = %s AND table_name = 'recordings'",
            (schema,),
        ).fetchall()
    return {r["column_name"] for r in rows}


def test_backfill_assigns_translate_by_id_marker_and_transcribe_otherwise(scoped_schema):
    cfg = _cfg()
    command.upgrade(cfg, PRE_SOURCE_REVISION)

    with _connect() as conn:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, created_at)"
            " VALUES ('u1', 'someone', 'x', now())"
        )
        conn.execute(
            "INSERT INTO recordings (id, user_id, wav_file, txt_file, started_at)"
            " VALUES ('20260101-000000-someone-abc123', 'u1', 'a.wav', 'a.txt', now())"
        )
        conn.execute(
            "INSERT INTO recordings (id, user_id, wav_file, txt_file, started_at)"
            " VALUES ('20260101-000000-someone-translate-def456', 'u1', 'b.wav', 'b.txt', now())"
        )

    command.upgrade(cfg, SOURCE_REVISION)

    with _connect() as conn:
        rows = conn.execute("SELECT id, source FROM recordings").fetchall()
    sources = {r["id"]: r["source"] for r in rows}
    assert sources["20260101-000000-someone-abc123"] == "transcribe"
    assert sources["20260101-000000-someone-translate-def456"] == "translate"


def test_source_is_not_null_and_constrained_to_known_values(scoped_schema):
    cfg = _cfg()
    command.upgrade(cfg, "head")

    with _connect() as conn:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, created_at)"
            " VALUES ('u1', 'someone', 'x', now())"
        )

        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO recordings"
                    " (id, user_id, wav_file, txt_file, started_at, source)"
                    " VALUES ('r-bad-source', 'u1', 'a.wav', 'a.txt', now(), 'bogus')"
                )

        with pytest.raises(psycopg.errors.NotNullViolation):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO recordings"
                    " (id, user_id, wav_file, txt_file, started_at)"
                    " VALUES ('r-no-source', 'u1', 'a.wav', 'a.txt', now())"
                )


def test_downgrade_removes_column_and_upgrade_restores_it(scoped_schema):
    cfg = _cfg()
    command.upgrade(cfg, "head")
    assert "source" in _recordings_columns(scoped_schema)

    command.downgrade(cfg, PRE_SOURCE_REVISION)
    assert "source" not in _recordings_columns(scoped_schema)

    command.upgrade(cfg, "head")
    assert "source" in _recordings_columns(scoped_schema)


@pytest.fixture
def reset_db_pool(monkeypatch):
    """db.verify_schema_current()/get_current_revision() go through
    db._get_pool(), unlike this file's other tests (which use raw psycopg
    connections directly) - reset the pool so it targets scoped_schema's
    DATABASE_URL instead of whatever a previous test's pool was cached
    against, and close it again afterward so nothing leaks past this test."""
    monkeypatch.setattr(db, "_pool", None)
    yield
    if db._pool is not None:
        db._pool.close()
        db._pool = None


def test_get_head_revision_matches_latest_migration_file():
    assert db.get_head_revision() == SOURCE_REVISION


def test_verify_schema_current_passes_once_migrated_to_head(scoped_schema, reset_db_pool):
    command.upgrade(_cfg(), "head")
    db.verify_schema_current()  # must not raise


def test_verify_schema_current_raises_when_behind_head(scoped_schema, reset_db_pool):
    command.upgrade(_cfg(), PRE_SOURCE_REVISION)
    with pytest.raises(RuntimeError):
        db.verify_schema_current()


def test_verify_schema_current_raises_on_never_migrated_database(scoped_schema, reset_db_pool):
    # No command.upgrade() at all - alembic_version doesn't exist yet,
    # simulating a fresh database nobody ran the migrate step against.
    with pytest.raises(RuntimeError):
        db.verify_schema_current()
