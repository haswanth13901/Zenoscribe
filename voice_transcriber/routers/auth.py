"""Login and the current-user lookup.

Note the two `auth` names in play here: this module is
`voice_transcriber.routers.auth` (the HTTP routes), while the `auth`
imported below is `voice_transcriber.auth` (the JWT/password service
they call into). Different packages, no shadowing.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

try:
    from .. import auth
    from .. import config
    from .. import db
except ImportError:  # run flat from inside the package dir
    import auth
    import config
    import db

log = logging.getLogger("api")

router = APIRouter()


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/api/login")
async def login(body: LoginBody, request: Request):
    client_ip = request.client.host if request.client else ""
    recent_failures = await asyncio.to_thread(
        db.count_recent_failed_logins, body.username, client_ip, config.LOGIN_ATTEMPT_WINDOW_SEC
    )
    if recent_failures >= config.LOGIN_ATTEMPT_LIMIT:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many login attempts, try again later",
        )

    row = await asyncio.to_thread(db.get_user_by_username, body.username)
    # Same message either way so the response can't be used to discover
    # which usernames exist.
    if not row or not await asyncio.to_thread(auth.verify_password, body.password, row["password_hash"]):
        await asyncio.to_thread(db.record_failed_login, body.username, client_ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if not row["is_active"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deactivated")
    await asyncio.to_thread(db.clear_failed_logins, body.username, client_ip)
    await asyncio.to_thread(db.touch_login, row["id"])
    return {
        "token": auth.make_token(row),
        "user": {
            "id": row["id"],
            "username": row["username"],
            "full_name": row["full_name"],
            "role": row["role"],
        },
    }


@router.get("/api/me")
async def me(user=Depends(auth.current_user)):
    return {
        "id": user["id"],
        "username": user["username"],
        "full_name": user["full_name"],
        "email": user["email"],
        "role": user["role"],
    }
