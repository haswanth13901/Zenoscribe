"""Batch (non-live) transcription: upload a file, get speaker turns back.

Both endpoints share the bounded upload executor and the best-effort
persistence helper defined here.
"""

import asyncio
import concurrent.futures
import functools
import logging
import mimetypes
import os
import tempfile
import uuid
import wave
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

try:
    from .. import auth
    from .. import config
    from .. import db
    from .. import rate_limit
    from .. import soniox_client as sx
    from .. import storage
except ImportError:  # run flat from inside the package dir
    import auth
    import config
    import db
    import rate_limit
    import soniox_client as sx
    import storage

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


def _persist_upload_recording(user, tmp_path, suffix, turns) -> bool:
    """Upload a successfully-transcribed upload into storage and register it
    as a recording, mirroring how transcribe.py/translate.py persist their
    live sessions - the batch-upload flow previously discarded both the
    audio and the transcript once the response was sent, so nothing showed
    up in My/All Recordings.

    Best-effort: storage/DB failures are logged, not raised, so a hiccup
    here doesn't turn an otherwise-successful transcription into a 500 for
    the caller. Returns True if the temp file was consumed by a successful
    upload (so the caller shouldn't also try to unlink it), False if
    nothing was persisted (empty result, or the upload itself failed) and
    the caller's own cleanup should run instead. Duration is read from
    tmp_path *before* uploading it - storage.upload() consumes (deletes)
    the local copy on success.

    Turns may or may not carry a "translation" key (present only for
    /transcribe/translate) - the transcript and preview include it when
    present, matching translate.py's live-session format. Runs on a worker
    thread (see _transcribe_file_bounded's caller), so storage calls here
    are made directly, not via asyncio.to_thread.
    """
    if not turns:
        return False

    started_at = datetime.now()
    stamp = started_at.strftime("%Y%m%d-%H%M%S")
    session = f"{stamp}-{user['username']}-upload-{uuid.uuid4().hex[:6]}"
    wav_key = storage.recording_key(user["id"], session, suffix)
    txt_key = storage.recording_key(user["id"], session, ".txt")

    duration = 0.0
    if suffix.lower() == ".wav":
        try:
            with wave.open(tmp_path, "rb") as wf:
                duration = wf.getnframes() / float(wf.getframerate() or 1)
        except (wave.Error, OSError):
            log.exception("could not read wav duration %s", tmp_path)

    content_type = mimetypes.guess_type(f"f{suffix}")[0] or "application/octet-stream"
    try:
        storage.get_storage().upload(wav_key, Path(tmp_path), content_type)
    except Exception:
        log.exception("could not store uploaded audio %s", wav_key)
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
        storage.get_storage().upload_text(txt_key, "\n".join(lines))
    except Exception:
        log.exception("could not write upload transcript %s", txt_key)

    preview = " ".join(t.get("translation") or t.get("text", "") for t in turns)[:160]
    try:
        db.add_recording(
            session, user["id"], wav_key, txt_key,
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
                    status.HTTP_413_CONTENT_TOO_LARGE,
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
                        status.HTTP_413_CONTENT_TOO_LARGE,
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
                    status.HTTP_413_CONTENT_TOO_LARGE,
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
                        status.HTTP_413_CONTENT_TOO_LARGE,
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
