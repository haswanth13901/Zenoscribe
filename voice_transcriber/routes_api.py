"""Authentication, user administration, and recording access.

Everything that decides *who* may see *what*. The transcription engine in
transcribe.py has no knowledge of these rules beyond calling
auth.user_from_ws() to identify the speaker at connection time.

This module is now a thin aggregator - the endpoints themselves live in
routers/, one module per domain (see routers/__init__.py). Sub-routers are
included in the order the routes were originally declared in, so FastAPI
matches them exactly as before.

The re-exports below are the module's established surface: tests reach for
routes_api.sx (to patch soniox_client.transcribe_file) and call
routes_api._persist_upload_recording directly. Each name below is the same
object as in the module that defines it, not a copy, so patching through
this module still reaches the code that runs.
"""

from fastapi import APIRouter

try:
    from . import soniox_client as sx
    from .routers import admin, auth, recordings, test_hooks, uploads
except ImportError:  # run flat from inside the package dir
    import soniox_client as sx
    from routers import admin, auth, recordings, test_hooks, uploads

USERNAME_RE = admin.USERNAME_RE
_rec_json = recordings._rec_json
_authorize_recording = recordings._authorize_recording
_persist_upload_recording = uploads._persist_upload_recording
_transcribe_file_bounded = uploads._transcribe_file_bounded
_UPLOAD_EXECUTOR = uploads._UPLOAD_EXECUTOR

router = APIRouter()
router.include_router(auth.router)
router.include_router(admin.router)
router.include_router(test_hooks.router)
router.include_router(recordings.router)
router.include_router(uploads.router)

__all__ = ["router", "sx", "USERNAME_RE"]
