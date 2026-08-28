"""Test-only hook for forcing soniox_client.transcribe_file failure modes.

Gated three ways - config.ALLOW_TEST_HOOKS (404 when off, so the
endpoint is invisible in production), a shared-secret header, and a
localhost restriction. Kept in its own module precisely because it is
not part of the real API surface.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

try:
    from .. import auth
    from .. import config
    from .. import soniox_client as sx
except ImportError:  # run flat from inside the package dir
    import auth
    import config
    import soniox_client as sx

log = logging.getLogger("api")

router = APIRouter()


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
