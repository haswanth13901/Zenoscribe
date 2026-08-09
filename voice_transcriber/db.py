"""SQLite storage for users and recording metadata.

Plain SQL throughout so this ports to Postgres by swapping the connection
and changing '?' placeholders to '%s'.
"""

import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

DB_PATH = Path("app.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL COLLATE NOCASE,
    full_name     TEXT NOT NULL DEFAULT '',
    email         TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user',
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    created_by    TEXT,
    last_login    TEXT,
    last_seen     TEXT
);

CREATE TABLE IF NOT EXISTS recordings (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    wav_file    TEXT NOT NULL,
    txt_file    TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    duration    REAL NOT NULL DEFAULT 0,
    turn_count  INTEGER NOT NULL DEFAULT 0,
    preview     TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS failed_logins (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT NOT NULL,
    ip           TEXT NOT NULL,
    attempted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_failed_logins_username_ip
    ON failed_logins(username, ip, attempted_at);

CREATE INDEX IF NOT EXISTS idx_rec_user ON recordings(user_id, started_at DESC);
"""


def connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init():
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        # Lightweight migration: add columns missing from older databases.
        # ALTER TABLE ADD COLUMN is a no-op-safe way to evolve the schema
        # without dropping data. Guarded so re-running init() is harmless.
        existing = {
            r["name"] for r in conn.execute("PRAGMA table_info(users)")
        }
        if "last_seen" not in existing:
            conn.execute("ALTER TABLE users ADD COLUMN last_seen TEXT")
        conn.commit()
    finally:
        conn.close()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _clean_login_key(value: str) -> str:
    return value.strip().lower()


def record_failed_login(username: str, ip: str):
    conn = connect()
    try:
        now = _now()
        conn.execute(
            "INSERT INTO failed_logins (username, ip, attempted_at) VALUES (?, ?, ?)",
            (_clean_login_key(username), ip or "", now),
        )
        conn.commit()
    finally:
        conn.close()


def clear_failed_logins(username: str, ip: str):
    conn = connect()
    try:
        conn.execute(
            "DELETE FROM failed_logins WHERE username = ? AND ip = ?",
            (_clean_login_key(username), ip or ""),
        )
        conn.commit()
    finally:
        conn.close()


def count_recent_failed_logins(username: str, ip: str, window_sec: int):
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_sec)
    conn = connect()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM failed_logins"
            " WHERE username = ? AND ip = ? AND attempted_at >= ?",
            (_clean_login_key(username), ip or "", cutoff.isoformat()),
        ).fetchone()["n"]
    finally:
        conn.close()


def create_user(username, password_hash, full_name="", email="",
                role="user", created_by=None):
    """Create a new user or update an existing one with the provided values.

    This makes test setup idempotent: if a user with the same username exists
    the record is updated with the supplied password and profile fields and
    the existing id is returned instead of failing on UNIQUE constraint.
    """
    uname = username.strip()
    conn = connect()
    try:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (uname,)
        ).fetchone()
        if existing:
            uid = existing["id"]
            conn.execute(
                """UPDATE users
                   SET password_hash = ?, full_name = ?, email = ?, role = ?, is_active = 1, created_by = ?
                   WHERE id = ?""",
                (password_hash, full_name.strip(), email.strip(), role, created_by, uid),
            )
            conn.commit()
            return uid
        uid = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO users
               (id, username, full_name, email, password_hash, role,
                is_active, created_at, created_by)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (uid, uname, full_name.strip(), email.strip(),
             password_hash, role, _now(), created_by),
        )
        conn.commit()
        return uid
    finally:
        conn.close()


def get_user_by_username(username) -> Optional[sqlite3.Row]:
    conn = connect()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
    finally:
        conn.close()


def get_user(user_id) -> Optional[sqlite3.Row]:
    conn = connect()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()


def list_users():
    conn = connect()
    try:
        return conn.execute(
            """SELECT u.*, COUNT(r.id) AS recording_count
               FROM users u
               LEFT JOIN recordings r ON r.user_id = u.id
               GROUP BY u.id
               ORDER BY u.created_at DESC"""
        ).fetchall()
    finally:
        conn.close()


def touch_login(user_id):
    conn = connect()
    try:
        now = _now()
        # Logging in also counts as being seen.
        conn.execute(
            "UPDATE users SET last_login = ?, last_seen = ? WHERE id = ?",
            (now, now, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def touch_seen(user_id):
    """Bump last_seen on any authenticated activity."""
    conn = connect()
    try:
        conn.execute(
            "UPDATE users SET last_seen = ? WHERE id = ?", (_now(), user_id)
        )
        conn.commit()
    finally:
        conn.close()


def set_active(user_id, active: bool):
    conn = connect()
    try:
        if active:
            result = conn.execute(
                "UPDATE users SET is_active = 1 WHERE id = ?",
                (user_id,),
            )
        else:
            result = conn.execute(
                """
                UPDATE users
                SET is_active = 0
                WHERE id = ?
                  AND NOT (
                      role = 'admin'
                      AND is_active = 1
                      AND (
                          SELECT COUNT(*)
                          FROM users
                          WHERE role = 'admin'
                            AND is_active = 1
                      ) = 1
                  )
                """,
                (user_id,),
            )
        conn.commit()
        return result.rowcount
    finally:
        conn.close()


def set_password(user_id, password_hash):
    conn = connect()
    try:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_user(user_id):
    """Returns the recording file stems so the caller can unlink them.

    The delete is conditional to avoid removing the last active admin.
    """
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT wav_file, txt_file FROM recordings WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        files = [(r["wav_file"], r["txt_file"]) for r in rows]
        result = conn.execute(
            """
            DELETE FROM users
            WHERE id = ?
              AND NOT (
                  role = 'admin'
                  AND is_active = 1
                  AND (
                      SELECT COUNT(*)
                      FROM users
                      WHERE role = 'admin'
                        AND is_active = 1
                  ) = 1
              )
            """,
            (user_id,),
        )
        conn.commit()
        if result.rowcount == 0:
            return None
        return files
    finally:
        conn.close()


def count_admins():
    conn = connect()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND is_active = 1"
        ).fetchone()["n"]
    finally:
        conn.close()


def add_recording(rec_id, user_id, wav_file, txt_file, started_at,
                  duration, turn_count, preview):
    """Insert or update a recording entry (idempotent on rec_id)."""
    conn = connect()
    try:
        existing = conn.execute(
            "SELECT id FROM recordings WHERE id = ?", (rec_id,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE recordings
                   SET user_id = ?, wav_file = ?, txt_file = ?, started_at = ?, duration = ?, turn_count = ?, preview = ?
                   WHERE id = ?""",
                (user_id, wav_file, txt_file, started_at, duration, turn_count, preview, rec_id),
            )
        else:
            conn.execute(
                """INSERT INTO recordings
                   (id, user_id, wav_file, txt_file, started_at,
                    duration, turn_count, preview)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (rec_id, user_id, wav_file, txt_file, started_at,
                 duration, turn_count, preview),
            )
        conn.commit()
    finally:
        conn.close()


def list_recordings(user_id=None, date_from=None, date_to=None, limit=200):
    """user_id=None returns every recording (admin view).

    date_from / date_to are ISO date strings (YYYY-MM-DD). The range is
    inclusive of both ends; date_to is matched up to the end of that day.
    """
    where = []
    params = []
    if user_id:
        where.append("r.user_id = ?")
        params.append(user_id)
    if date_from:
        where.append("r.started_at >= ?")
        params.append(f"{date_from}T00:00:00")
    if date_to:
        where.append("r.started_at <= ?")
        params.append(f"{date_to}T23:59:59.999999")

    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)

    conn = connect()
    try:
        return conn.execute(
            f"""SELECT r.*, u.username
                FROM recordings r JOIN users u ON u.id = r.user_id
                {clause}
                ORDER BY r.started_at DESC LIMIT ?""",
            params,
        ).fetchall()
    finally:
        conn.close()


def get_recording(rec_id) -> Optional[sqlite3.Row]:
    conn = connect()
    try:
        return conn.execute(
            """SELECT r.*, u.username
               FROM recordings r JOIN users u ON u.id = r.user_id
               WHERE r.id = ?""",
            (rec_id,),
        ).fetchone()
    finally:
        conn.close()


def delete_recording(rec_id):
    conn = connect()
    try:
        row = conn.execute(
            "SELECT wav_file, txt_file FROM recordings WHERE id = ?", (rec_id,)
        ).fetchone()
        conn.execute("DELETE FROM recordings WHERE id = ?", (rec_id,))
        conn.commit()
        return (row["wav_file"], row["txt_file"]) if row else None
    finally:
        conn.close()