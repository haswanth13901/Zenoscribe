"""Recording listing, transcript/audio download, and deletion.

Ownership is enforced by _authorize_recording, which 404s rather than
403s on someone else's recording so IDs stay undiscoverable.
"""

import asyncio
import logging
import mimetypes
import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

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
    try:
        text = await asyncio.to_thread(storage.get_storage().get_text, row["txt_file"])
    except storage.StorageNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transcript missing")
    except Exception:
        # Distinct from "missing" above: the object may well exist, but the
        # storage backend itself (MinIO/disk) couldn't be reached right now
        # - a 503 tells the client "try again shortly," not "this recording
        # doesn't exist," which a 404 here would incorrectly imply.
        log.exception("storage backend error reading transcript %s", row["txt_file"])
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Storage temporarily unavailable")
    return {"id": rec_id, "text": text}


@router.get("/api/recordings/{rec_id}/audio")
async def get_audio(
    rec_id: str,
    user=Depends(auth.current_user),
    _rl=Depends(rate_limit.per_user(120, 60, "recordings")),
):
    row = await _authorize_recording(rec_id, user)
    # Recordings from the batch-upload flow keep their original extension
    # (mp3, etc), unlike live sessions which are always .wav - guess the
    # content type instead of assuming .wav for everything.
    suffix = os.path.splitext(row["wav_file"])[1] or ".wav"
    media_type = mimetypes.guess_type(row["wav_file"])[0] or "audio/wav"
    try:
        stream = await asyncio.to_thread(storage.get_storage().open_stream, row["wav_file"])
    except storage.StorageNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Audio missing")
    except Exception:
        # See get_transcript's identical distinction above: "backend
        # unreachable" (503, try again) is not "object doesn't exist" (404).
        log.exception("storage backend error reading audio %s", row["wav_file"])
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Storage temporarily unavailable")

    def _iter_and_close():
        # Starlette runs a sync generator in a threadpool automatically
        # (see StreamingResponse), so stream.read()'s blocking I/O here
        # doesn't stall the event loop.
        try:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            stream.close()

    return StreamingResponse(
        _iter_and_close(),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{rec_id}{suffix}"'},
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
        for key in files:
            try:
                await asyncio.to_thread(storage.get_storage().delete, key)
            except Exception:
                log.warning("could not remove %s", key)
    return {"ok": True}
