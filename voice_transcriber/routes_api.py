"""Authentication, user administration, and recording access.

Everything that decides *who* may see *what*. The transcription engine in
transcribe.py has no knowledge of these rules beyond calling
auth.user_from_ws() to identify the speaker at connection time.
"""

import asyncio
import concurrent.futures
import functools
import logging
import mimetypes
import os
import shutil
import tempfile
import uuid
import wave
from datetime import datetime

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel

try:
    from . import auth
    from . import config
    from . import db
    from . import rate_limit
    from . import soniox_client as sx
except ImportError:  # run flat from inside the package dir
    import auth
    import config
    import db
    import rate_limit
    import soniox_client as sx

log = logging.getLogger("api")

router = APIRouter()

# sx.transcribe_file blocks a thread for up to the Soniox transcription
# timeout (minutes, for a long file). asyncio.to_thread would run it on the
# loop's shared default executor - the same pool that serves
# db.touch_seen (every authenticated request) and writeframes (every audio
# chunk of every live session, in transcribe.py/translate.py). A handful of
# simultaneous uploads could exhaust that pool and stall live transcription
# with nothing in the logs to explain it. Give uploads their own small,
# separately bounded pool instead.
_UPLOAD_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=3, thread_name_prefix="upload-transcribe",
)


async def _transcribe_file_bounded(*args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _UPLOAD_EXECUTOR, functools.partial(sx.transcribe_file, *args, **kwargs)
    )


class LoginBody(BaseModel):
    username: str
    password: str


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
    for wav_name, txt_name in files:
        for name in (wav_name, txt_name):
            try:
                (config.RECORDINGS / name).unlink(missing_ok=True)
            except OSError:
                log.warning("could not remove %s", name)
    return {"ok": True, "removed_recordings": len(files)}


@router.post("/internal/test-hook/transcribe_mode")
async def set_transcribe_fake_mode(request: Request, payload: dict, admin=Depends(auth.current_admin)):
    """Set a test-only fake mode for soniox_client.transcribe_file.

    Allowed modes: 'timeout', 'runtime', 'ok', or null to clear.
    This endpoint is gated by config.ALLOW_TEST_HOOKS and requires an
    additional X-TEST-HOOK-SECRET header if TEST_HOOK_SECRET is set. It is
    also restricted to localhost when RESTRICT_TEST_HOOK_TO_LOCALHOST is True.
    """
    if not config.ALLOW_TEST_HOOKS:
        # Hide the endpoint in production by returning 404
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    secret = request.headers.get("x-test-hook-secret")
    if config.TEST_HOOK_SECRET and secret != config.TEST_HOOK_SECRET:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid test hook secret")

    if config.RESTRICT_TEST_HOOK_TO_LOCALHOST:
        client_host = request.client.host if request.client else None
        if client_host not in ("127.0.0.1", "::1", "localhost"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Test hook allowed only from localhost")

    mode = payload.get("mode") if isinstance(payload, dict) else None
    if mode is None:
        sx.set_test_fake_mode(None)
        log.info("test hook: cleared fake transcribe mode (by %s)", admin["username"]) if admin else None
        return {"ok": True, "mode": None}
    if mode not in ("timeout", "runtime", "ok"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid mode")
    sx.set_test_fake_mode(mode)
    log.info("test hook: set fake transcribe mode=%s (by %s)", mode, admin["username"]) if admin else None
    return {"ok": True, "mode": mode}


def _rec_json(r):
    return {
        "id": r["id"],
        "username": r["username"],
        "user_id": r["user_id"],
        "started_at": r["started_at"],
        "duration": round(r["duration"], 1),
        "turn_count": r["turn_count"],
        "preview": r["preview"],
        "source": r["source"],
    }


@router.get("/api/recordings")
async def list_recordings(
    user_id: str = None,
    date_from: str = None,
    date_to: str = None,
    source: str = None,
    user=Depends(auth.current_user),
    _rl=Depends(rate_limit.per_user(120, 60, "recordings")),
):
    """Users see only their own. Admins see all, optionally filtered by user.
    All roles can additionally filter by an inclusive date range (YYYY-MM-DD)
    and/or by recording source. An unrecognized source or a malformed date
    is a 400, not a 500 (unguarded strptime) or a silently empty list."""
    if source is not None and source not in db.RECORDING_SOURCES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Invalid source; must be one of {', '.join(db.RECORDING_SOURCES)}",
        )
    scope = user_id if user["role"] == "admin" else user["id"]
    try:
        rows = await asyncio.to_thread(
            db.list_recordings,
            user_id=scope, date_from=date_from, date_to=date_to, source=source
        )
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Invalid date_from/date_to; expected YYYY-MM-DD"
        )
    return [_rec_json(r) for r in rows]


async def _authorize_recording(rec_id, user):
    row = await asyncio.to_thread(db.get_recording, rec_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found")
    if user["role"] != "admin" and row["user_id"] != user["id"]:
        # 404 rather than 403 so IDs belonging to others aren't discoverable.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found")
    return row


@router.get("/api/recordings/{rec_id}/transcript")
async def get_transcript(
    rec_id: str,
    user=Depends(auth.current_user),
    _rl=Depends(rate_limit.per_user(120, 60, "recordings")),
):
    row = await _authorize_recording(rec_id, user)
    path = config.RECORDINGS / row["txt_file"]
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transcript missing")
    return {"id": rec_id, "text": path.read_text(encoding="utf-8")}


@router.get("/api/recordings/{rec_id}/audio")
async def get_audio(
    rec_id: str,
    user=Depends(auth.current_user),
    _rl=Depends(rate_limit.per_user(120, 60, "recordings")),
):
    row = await _authorize_recording(rec_id, user)
    path = config.RECORDINGS / row["wav_file"]
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Audio missing")
    # Recordings from the batch-upload flow keep their original extension
    # (mp3, etc), unlike live sessions which are always .wav - guess the
    # content type instead of assuming .wav for everything.
    media_type = mimetypes.guess_type(path.name)[0] or "audio/wav"
    return FileResponse(
        path, media_type=media_type, filename=f"{rec_id}{path.suffix}"
    )


@router.delete("/api/recordings/{rec_id}")
async def remove_recording(
    rec_id: str,
    user=Depends(auth.current_user),
    _rl=Depends(rate_limit.per_user(120, 60, "recordings")),
):
    await _authorize_recording(rec_id, user)
    files = await asyncio.to_thread(db.delete_recording, rec_id)
    if files:
        for name in files:
            try:
                (config.RECORDINGS / name).unlink(missing_ok=True)
            except OSError:
                log.warning("could not remove %s", name)
    return {"ok": True}


def _persist_upload_recording(user, tmp_path, suffix, turns) -> bool:
    """Move a successfully-transcribed upload into permanent storage and
    register it as a recording, mirroring how transcribe.py/translate.py
    persist their live sessions - the batch-upload flow previously
    discarded both the audio and the transcript once the response was
    sent, so nothing showed up in My/All Recordings.

    Best-effort: storage/DB failures are logged, not raised, so a hiccup
    here doesn't turn an otherwise-successful transcription into a 500 for
    the caller. Returns True if the temp file was moved (so the caller
    shouldn't also try to unlink it), False if nothing was persisted (empty
    result, or the move itself failed) and the caller's own cleanup should
    run instead.

    Turns may or may not carry a "translation" key (present only for
    /transcribe/translate) - the transcript and preview include it when
    present, matching translate.py's live-session format.
    """
    if not turns:
        return False

    started_at = datetime.now()
    stamp = started_at.strftime("%Y%m%d-%H%M%S")
    session = f"{stamp}-{user['username']}-upload-{uuid.uuid4().hex[:6]}"
    audio_path = config.RECORDINGS / f"{session}{suffix}"
    txt_path = config.RECORDINGS / f"{session}.txt"

    try:
        shutil.move(tmp_path, audio_path)
    except OSError:
        log.exception("could not store uploaded audio %s", audio_path)
        return False

    lines = []
    for t in turns:
        speaker = t.get("speaker") or "user-1"
        start = t.get("start") or 0.0
        line = f"[{start:.1f}s] {speaker}: {t.get('text', '')}"
        if "translation" in t:
            line += f"\n    -> {t['translation']}"
        lines.append(line)
    try:
        txt_path.write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        log.exception("could not write upload transcript %s", txt_path)

    duration = 0.0
    if suffix.lower() == ".wav":
        try:
            with wave.open(str(audio_path), "rb") as wf:
                duration = wf.getnframes() / float(wf.getframerate() or 1)
        except (wave.Error, OSError):
            log.exception("could not read wav duration %s", audio_path)

    preview = " ".join(t.get("translation") or t.get("text", "") for t in turns)[:160]
    try:
        db.add_recording(
            session, user["id"], audio_path.name, txt_path.name,
            started_at.isoformat(), duration, len(turns), preview, "upload",
        )
    except Exception:
        log.exception("could not register upload recording %s", session)

    return True


@router.post("/api/transcribe")
async def transcribe_upload(
    request: Request,
    file: UploadFile = File(...),
    num_speakers: int = Form(None),
    user=Depends(auth.current_user),
    _rl=Depends(rate_limit.per_user(15, 300, "upload")),
):
    """Batch endpoint - upload a wav/mp3, get turns back."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > config.MAX_UPLOAD_SIZE:
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    f"Upload exceeds maximum size of {config.MAX_UPLOAD_MB}MB",
                )
        except ValueError:
            pass

    suffix = os.path.splitext(file.filename)[1] or ".wav"
    path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            path = tmp.name
            size = 0
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > config.MAX_UPLOAD_SIZE:
                    # Ensure the tmp file is removed before returning a 413.
                    tmp.close()
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        f"Upload exceeds maximum size of {config.MAX_UPLOAD_MB}MB",
                    )
                tmp.write(chunk)

        try:
            turns = await _transcribe_file_bounded(path, num_speakers=num_speakers)
        except TimeoutError as e:
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, f"Transcription timed out: {e}")
        except RuntimeError as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Transcription service error: {e}")
        except Exception as e:
            log.exception("unexpected error during transcription: %s", e)
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal transcription error")

        if await asyncio.to_thread(_persist_upload_recording, user, path, suffix, turns):
            path = None  # ownership moved to permanent storage
        return {"turns": turns}
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                log.exception("could not delete temp upload %s", path)


@router.post("/api/transcribe/translate")
async def transcribe_and_translate(
    request: Request,
    file: UploadFile = File(...),
    target_language: str = None,
    num_speakers: int = Form(None),
    user=Depends(auth.current_user),
    _rl=Depends(rate_limit.per_user(15, 300, "upload")),
):
    """Upload audio, run STT and server-side one-way translation (Soniox), and
    return translated speaker turns. If target_language is omitted, behaves
    like /api/transcribe but is still useful as a distinct endpoint.
    """
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > config.MAX_UPLOAD_SIZE:
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    f"Upload exceeds maximum size of {config.MAX_UPLOAD_MB}MB",
                )
        except ValueError:
            pass

    suffix = os.path.splitext(file.filename)[1] or ".wav"
    path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            path = tmp.name
            size = 0
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > config.MAX_UPLOAD_SIZE:
                    tmp.close()
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        f"Upload exceeds maximum size of {config.MAX_UPLOAD_MB}MB",
                    )
                tmp.write(chunk)

        try:
            turns = await _transcribe_file_bounded(
                path, target_language=target_language, num_speakers=num_speakers
            )
        except TimeoutError as e:
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, f"Transcription timed out: {e}")
        except RuntimeError as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Transcription service error: {e}")
        except Exception as e:
            log.exception("unexpected error during transcribe+translate: %s", e)
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal transcription error")

        if await asyncio.to_thread(_persist_upload_recording, user, path, suffix, turns):
            path = None  # ownership moved to permanent storage
        return {"turns": turns}
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                log.exception("could not delete temp upload %s", path)
