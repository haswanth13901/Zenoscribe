"""SQLite storage for users and recording metadata.

Plain SQL throughout so this ports to Postgres by swapping the connection
and changing '?' placeholders to '%s'.
"""

import sqlite3
import uuid
from datetime import datetime, timezone
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


# ---------------------------------------------------------------- users


def create_user(username, password_hash, full_name="", email="",
                role="user", created_by=None):
    uid = uuid.uuid4().hex
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO users
               (id, username, full_name, email, password_hash, role,
                is_active, created_at, created_by)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (uid, username.strip(), full_name.strip(), email.strip(),
             password_hash, role, _now(), created_by),
        )
        conn.commit()
    finally:
        conn.close()
    return uid


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
        conn.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (1 if active else 0, user_id),
        )
        conn.commit()
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
    """Returns the recording file stems so the caller can unlink them."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT wav_file, txt_file FROM recordings WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        files = [(r["wav_file"], r["txt_file"]) for r in rows]
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
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


# ----------------------------------------------------------- recordings


def add_recording(rec_id, user_id, wav_file, txt_file, started_at,
                  duration, turn_count, preview):
    conn = connect()
    try:
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
        # '<=' against end-of-day so the whole 'to' date is included.
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