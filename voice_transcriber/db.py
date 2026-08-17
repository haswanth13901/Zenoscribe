"""Postgres storage for users and recording metadata.

Plain SQL throughout via psycopg - no ORM. Schema lives in Alembic
migrations (../alembic/versions/), not in this file.
"""

import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config as app_config

REPO_ROOT = Path(__file__).resolve().parent.parent

# The set of valid `recordings.source` values - what produced the recording.
# Kept here (not just as a DB CHECK constraint) so routes_api.py can validate
# an incoming filter value without a round-trip to Postgres.
RECORDING_SOURCES = ("transcribe", "translate", "upload")

_pool: Optional[ConnectionPool] = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            app_config.DATABASE_URL,
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _pool


def close_pool():
    """Close the connection pool. Called from the app's shutdown hook."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def init():
    """Apply all pending Alembic migrations. Idempotent - safe to call on
    every startup, including against an already-up-to-date database."""
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    command.upgrade(cfg, "head")


def _now():
    return datetime.now(timezone.utc)


def _parse_ts(value):
    """Accept a datetime or an ISO string. Naive strings are treated as UTC,
    matching the old SQLite TEXT column's "store exactly what was given"
    behavior instead of letting Postgres reinterpret via session timezone.
    """
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _clean_login_key(value: str) -> str:
    return value.strip().lower()


def record_failed_login(username: str, ip: str):
    with _get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO failed_logins (username, ip, attempted_at) VALUES (%s, %s, %s)",
            (_clean_login_key(username), ip or "", _now()),
        )


def clear_failed_logins(username: str, ip: str):
    with _get_pool().connection() as conn:
        conn.execute(
            "DELETE FROM failed_logins WHERE username = %s AND ip = %s",
            (_clean_login_key(username), ip or ""),
        )


def count_recent_failed_logins(username: str, ip: str, window_sec: int):
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_sec)
    with _get_pool().connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM failed_logins"
            " WHERE username = %s AND ip = %s AND attempted_at >= %s",
            (_clean_login_key(username), ip or "", cutoff),
        ).fetchone()["n"]


def create_user(username, password_hash, full_name="", email="",
                role="user", created_by=None):
    """Create a new user or update an existing one with the provided values.

    This makes test setup idempotent: if a user with the same username exists
    the record is updated with the supplied password and profile fields and
    the existing id is returned instead of failing on the UNIQUE constraint.
    """
    uname = username.strip()
    uid = uuid.uuid4().hex
    with _get_pool().connection() as conn:
        row = conn.execute(
            """INSERT INTO users
               (id, username, full_name, email, password_hash, role,
                is_active, created_at, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s, %s)
               ON CONFLICT (username) DO UPDATE
               SET password_hash = EXCLUDED.password_hash,
                   full_name = EXCLUDED.full_name,
                   email = EXCLUDED.email,
                   role = EXCLUDED.role,
                   is_active = TRUE,
                   created_by = EXCLUDED.created_by
               RETURNING id""",
            (uid, uname, full_name.strip(), email.strip(),
             password_hash, role, _now(), created_by),
        ).fetchone()
        return row["id"]


def get_user_by_username(username) -> Optional[dict]:
    with _get_pool().connection() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE username = %s", (username.strip(),)
        ).fetchone()


def get_user(user_id) -> Optional[dict]:
    with _get_pool().connection() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE id = %s", (user_id,)
        ).fetchone()


def list_users():
    with _get_pool().connection() as conn:
        return conn.execute(
            """SELECT u.*, COUNT(r.id) AS recording_count
               FROM users u
               LEFT JOIN recordings r ON r.user_id = u.id
               GROUP BY u.id
               ORDER BY u.created_at DESC"""
        ).fetchall()


def touch_login(user_id):
    with _get_pool().connection() as conn:
        # Logging in also counts as being seen.
        now = _now()
        conn.execute(
            "UPDATE users SET last_login = %s, last_seen = %s WHERE id = %s",
            (now, now, user_id),
        )


def touch_seen(user_id):
    """Bump last_seen on any authenticated activity."""
    with _get_pool().connection() as conn:
        conn.execute(
            "UPDATE users SET last_seen = %s WHERE id = %s", (_now(), user_id)
        )


def set_active(user_id, active: bool):
    with _get_pool().connection() as conn:
        if active:
            result = conn.execute(
                "UPDATE users SET is_active = TRUE WHERE id = %s",
                (user_id,),
            )
        else:
            result = conn.execute(
                """
                UPDATE users
                SET is_active = FALSE
                WHERE id = %s
                  AND NOT (
                      role = 'admin'
                      AND is_active = TRUE
                      AND (
                          SELECT COUNT(*)
                          FROM users
                          WHERE role = 'admin'
                            AND is_active = TRUE
                      ) = 1
                  )
                """,
                (user_id,),
            )
        return result.rowcount


def set_password(user_id, password_hash):
    with _get_pool().connection() as conn:
        conn.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (password_hash, user_id),
        )


def delete_user(user_id):
    """Returns the recording file stems so the caller can unlink them.

    The delete is conditional to avoid removing the last active admin.
    """
    with _get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT wav_file, txt_file FROM recordings WHERE user_id = %s",
            (user_id,),
        ).fetchall()
        files = [(r["wav_file"], r["txt_file"]) for r in rows]
        result = conn.execute(
            """
            DELETE FROM users
            WHERE id = %s
              AND NOT (
                  role = 'admin'
                  AND is_active = TRUE
                  AND (
                      SELECT COUNT(*)
                      FROM users
                      WHERE role = 'admin'
                        AND is_active = TRUE
                  ) = 1
              )
            """,
            (user_id,),
        )
        if result.rowcount == 0:
            return None
        return files


def count_admins():
    with _get_pool().connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND is_active = TRUE"
        ).fetchone()["n"]


def add_recording(rec_id, user_id, wav_file, txt_file, started_at,
                  duration, turn_count, preview, source):
    """Insert or update a recording entry (idempotent on rec_id).

    `source` is required (one of RECORDING_SOURCES) rather than defaulted,
    so a caller can't silently omit it and get a value that hides the bug.
    """
    with _get_pool().connection() as conn:
        conn.execute(
            """INSERT INTO recordings
               (id, user_id, wav_file, txt_file, started_at,
                duration, turn_count, preview, source)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE
               SET user_id = EXCLUDED.user_id,
                   wav_file = EXCLUDED.wav_file,
                   txt_file = EXCLUDED.txt_file,
                   started_at = EXCLUDED.started_at,
                   duration = EXCLUDED.duration,
                   turn_count = EXCLUDED.turn_count,
                   preview = EXCLUDED.preview,
                   source = EXCLUDED.source""",
            (rec_id, user_id, wav_file, txt_file, _parse_ts(started_at),
             duration, turn_count, preview, source),
        )


def list_recordings(user_id=None, date_from=None, date_to=None, source=None, limit=200):
    """user_id=None returns every recording (admin view).

    date_from / date_to are ISO date strings (YYYY-MM-DD), interpreted as
    UTC calendar days. The range is inclusive of both ends. Raises ValueError
    on a malformed date string - callers (routes_api.py) are expected to
    translate that into an HTTP 400 rather than letting it become a 500.
    """
    where = []
    params = []
    if user_id:
        where.append("r.user_id = %s")
        params.append(user_id)
    if date_from:
        where.append("r.started_at >= %s")
        params.append(datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc))
    if date_to:
        where.append("r.started_at < %s")
        params.append(
            datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            + timedelta(days=1)
        )
    if source:
        where.append("r.source = %s")
        params.append(source)

    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)

    with _get_pool().connection() as conn:
        return conn.execute(
            f"""SELECT r.*, u.username
                FROM recordings r JOIN users u ON u.id = r.user_id
                {clause}
                ORDER BY r.started_at DESC LIMIT %s""",
            params,
        ).fetchall()


def get_recording(rec_id) -> Optional[dict]:
    with _get_pool().connection() as conn:
        return conn.execute(
            """SELECT r.*, u.username
               FROM recordings r JOIN users u ON u.id = r.user_id
               WHERE r.id = %s""",
            (rec_id,),
        ).fetchone()


def delete_recording(rec_id):
    with _get_pool().connection() as conn:
        row = conn.execute(
            "SELECT wav_file, txt_file FROM recordings WHERE id = %s", (rec_id,)
        ).fetchone()
        conn.execute("DELETE FROM recordings WHERE id = %s", (rec_id,))
        return (row["wav_file"], row["txt_file"]) if row else None
