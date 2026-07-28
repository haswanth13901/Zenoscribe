"""JWT auth, password hashing, and role guards."""

import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import db

load_dotenv()

# Generated if absent so first run works, but set it in .env for production -
# a rotating secret invalidates every token on restart.
JWT_SECRET = os.environ.get("JWT_SECRET") or secrets.token_urlsafe(48)
JWT_ALGO = "HS256"
TOKEN_HOURS = int(os.environ.get("TOKEN_HOURS", "12"))

bearer = HTTPBearer(auto_error=False)


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def make_token(user_row) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_row["id"],
        "username": user_row["username"],
        "role": user_row["role"],
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_token(token: str):
    """Returns the payload, or None if invalid/expired."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.PyJWTError:
        return None


def user_from_token(token: str):
    """Resolve a token to a live, active user row."""
    payload = decode_token(token)
    if not payload:
        return None
    row = db.get_user(payload.get("sub"))
    # Re-check against the DB so deactivation takes effect immediately
    # rather than waiting for the token to expire.
    if not row or not row["is_active"]:
        return None
    return row


async def current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
):
    if not creds:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Not authenticated"
        )
    row = user_from_token(creds.credentials)
    if not row:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired session"
        )
    # Every authenticated request refreshes presence. Cheap single-row update.
    db.touch_seen(row["id"])
    return row


async def current_admin(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user


def user_from_ws(websocket: Request) -> object:
    """WebSockets can't send Authorization headers from the browser,
    so the token arrives as a query parameter instead."""
    token = websocket.query_params.get("token", "")
    return user_from_token(token) if token else None


def ensure_seed_admin():
    """Create the first admin if no admin exists yet."""
    if db.count_admins() > 0:
        return None
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "")
    generated = False
    if not password:
        password = secrets.token_urlsafe(12)
        generated = True
    if db.get_user_by_username(username):
        return None
    db.create_user(
        username=username,
        password_hash=hash_password(password),
        full_name="Super Admin",
        role="admin",
    )
    return (username, password if generated else None)