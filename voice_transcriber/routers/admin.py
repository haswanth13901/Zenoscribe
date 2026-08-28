"""User administration: list, create, reset password, activate, delete.

Every route here is behind auth.current_admin. The self- and
last-admin guards live with the routes that enforce them.
"""

import asyncio
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

try:
    from .. import auth
    from .. import db
    from .. import rate_limit
    from .. import storage
except ImportError:  # run flat from inside the package dir
    import auth
    import db
    import rate_limit
    import storage

log = logging.getLogger("api")

router = APIRouter()


# A username becomes part of every recording's storage key/scratch filename
# for that user (session names in transcribe.py/translate.py/
# _persist_upload_recording embed it directly). Restricting it to a safe
# charset closes off path-traversal via a crafted username (e.g.
# "../../etc") reaching storage.recording_key() -> a local-backend
# filesystem path - found and fixed during this pass's storage-abstraction
# security review, not previously exploitable-by-a-non-admin since only
# admins can set a username, but worth closing regardless (see
# recording_key()'s own defensive check in storage/base.py for the second
# layer of protection).
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class NewUserBody(BaseModel):
    username: str
    password: str
    full_name: str = ""
    email: str = ""
    role: str = "user"


class PasswordBody(BaseModel):
    password: str


class ActiveBody(BaseModel):
    is_active: bool


@router.get("/api/admin/users")
async def admin_list_users(_=Depends(auth.current_admin)):
    return [
        {
            "id": r["id"],
            "username": r["username"],
            "full_name": r["full_name"],
            "email": r["email"],
            "role": r["role"],
            "is_active": bool(r["is_active"]),
            "created_at": r["created_at"],
            "last_login": r["last_login"],
            "last_seen": r["last_seen"],
            "recording_count": r["recording_count"],
        }
        for r in await asyncio.to_thread(db.list_users)
    ]


@router.post("/api/admin/users")
async def admin_create_user(
    body: NewUserBody,
    admin=Depends(auth.current_admin),
    _rl=Depends(rate_limit.per_user(60, 60, "admin-write")),
):
    if not body.username.strip() or len(body.password) < auth.MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Username required and password must be at least {auth.MIN_PASSWORD_LENGTH} characters",
        )
    if not USERNAME_RE.match(body.username.strip()) or ".." in body.username:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Username may only contain letters, numbers, '.', '_', and '-' "
            "(and no repeated '.')",
        )
    if body.role not in ("user", "admin"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid role")
    if await asyncio.to_thread(db.get_user_by_username, body.username):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")
    password_hash = await asyncio.to_thread(auth.hash_password, body.password)
    uid = await asyncio.to_thread(
        db.create_user,
        username=body.username,
        password_hash=password_hash,
        full_name=body.full_name,
        email=body.email,
        role=body.role,
        created_by=admin["id"],
    )
    return {"id": uid, "username": body.username.strip(), "role": body.role}


@router.post("/api/admin/users/{user_id}/password")
async def admin_reset_password(
    user_id: str,
    body: PasswordBody,
    _=Depends(auth.current_admin),
    _rl=Depends(rate_limit.per_user(60, 60, "admin-write")),
):
    if len(body.password) < auth.MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Password must be at least {auth.MIN_PASSWORD_LENGTH} characters",
        )
    if not await asyncio.to_thread(db.get_user, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    password_hash = await asyncio.to_thread(auth.hash_password, body.password)
    await asyncio.to_thread(db.set_password, user_id, password_hash)
    return {"ok": True}


@router.post("/api/admin/users/{user_id}/active")
async def admin_set_active(
    user_id: str,
    body: ActiveBody,
    admin=Depends(auth.current_admin),
    _rl=Depends(rate_limit.per_user(60, 60, "admin-write")),
):
    target = await asyncio.to_thread(db.get_user, user_id)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    # Guard against an admin locking themselves - and possibly everyone -
    # out of the system.
    if not body.is_active:
        if str(target["id"]) == str(admin["id"]):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Cannot deactivate yourself"
            )
        if target["role"] == "admin" and await asyncio.to_thread(db.count_admins) <= 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Cannot deactivate the last admin"
            )
        updated = await asyncio.to_thread(db.set_active, user_id, body.is_active)
        if not updated:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Cannot deactivate the last admin"
            )
    else:
        await asyncio.to_thread(db.set_active, user_id, body.is_active)
    return {"ok": True}


@router.delete("/api/admin/users/{user_id}")
async def admin_delete_user(
    user_id: str,
    admin=Depends(auth.current_admin),
    _rl=Depends(rate_limit.per_user(60, 60, "admin-write")),
):
    target = await asyncio.to_thread(db.get_user, user_id)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if str(target["id"]) == str(admin["id"]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete yourself")
    if target["role"] == "admin" and await asyncio.to_thread(db.count_admins) <= 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Cannot delete the last admin"
        )
    files = await asyncio.to_thread(db.delete_user, user_id)
    if files is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Cannot delete the last admin"
        )
    for wav_key, txt_key in files:
        for key in (wav_key, txt_key):
            try:
                await asyncio.to_thread(storage.get_storage().delete, key)
            except Exception:
                log.warning("could not remove %s", key)
    return {"ok": True, "removed_recordings": len(files)}
