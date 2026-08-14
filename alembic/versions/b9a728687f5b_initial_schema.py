"""initial schema

Revision ID: b9a728687f5b
Revises:
Create Date: 2026-08-13 22:11:42.387695

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b9a728687f5b'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CITEXT gives case-insensitive comparison/uniqueness at the DB level,
    # matching the previous SQLite `COLLATE NOCASE` behavior on username.
    # Installed into a fixed schema (public) and referenced fully-qualified
    # below - deliberately independent of search_path, since per-test runs
    # use a search_path scoped to a single schema (see tests/conftest.py)
    # and must not need `public` on the path just to see this type.
    op.execute("CREATE EXTENSION IF NOT EXISTS citext SCHEMA public")

    op.execute("""
        CREATE TABLE users (
            id            TEXT PRIMARY KEY,
            username      public.citext UNIQUE NOT NULL,
            full_name     TEXT NOT NULL DEFAULT '',
            email         TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'user',
            is_active     BOOLEAN NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMPTZ NOT NULL,
            created_by    TEXT,
            last_login    TIMESTAMPTZ,
            last_seen     TIMESTAMPTZ
        )
    """)

    op.execute("""
        CREATE TABLE recordings (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            wav_file    TEXT NOT NULL,
            txt_file    TEXT NOT NULL,
            started_at  TIMESTAMPTZ NOT NULL,
            duration    REAL NOT NULL DEFAULT 0,
            turn_count  INTEGER NOT NULL DEFAULT 0,
            preview     TEXT NOT NULL DEFAULT ''
        )
    """)

    op.execute("""
        CREATE TABLE failed_logins (
            id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            username     TEXT NOT NULL,
            ip           TEXT NOT NULL,
            attempted_at TIMESTAMPTZ NOT NULL
        )
    """)

    op.execute(
        "CREATE INDEX idx_failed_logins_username_ip "
        "ON failed_logins(username, ip, attempted_at)"
    )
    op.execute(
        "CREATE INDEX idx_rec_user ON recordings(user_id, started_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS failed_logins")
    op.execute("DROP TABLE IF EXISTS recordings")
    op.execute("DROP TABLE IF EXISTS users")
