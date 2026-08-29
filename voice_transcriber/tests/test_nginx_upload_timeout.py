"""The nginx/batch-upload timeout invariant, asserted across both files.

`location /api/` in frontend/nginx.conf and soniox_client.BATCH_POLL_TIMEOUT
are one design decision written down in two places, in two languages, that
nothing else connects. Left at nginx's default proxy_read_timeout of 60s,
`location /api/` cut every upload that took longer than a minute with a 504
while routers/uploads.py carried on, finished, and called
_persist_upload_recording - the user was told it failed and then found the
recording in My Recordings, so they re-uploaded and paid Soniox twice.

Pure file parsing: no Docker, no nginx, no network, so this runs in the fast
suite. It reads the timeouts back out of the module rather than hardcoding
them, so tuning any of them re-derives the requirement instead of quietly
invalidating this test.
"""
import re
from pathlib import Path

from voice_transcriber import soniox_client as sx

NGINX_CONF = Path(__file__).resolve().parents[2] / "frontend" / "nginx.conf"

# uploads.py's _UPLOAD_EXECUTOR. run_in_executor queues with no timeout of
# its own, so once the pool is saturated a request's queue wait is simply
# added to its own processing time, against the same nginx budget.
UPLOAD_POOL_WORKERS = 3

# Concurrent uploads the edge budget is sized to absorb. Requests beyond the
# pool's 3 workers wait ceil((n - workers) / workers) full service times, so
# 6 is "one queued round behind a full pool" - the point past which more
# nginx headroom stops being the right fix and the async job API (see
# docs/audits/DEPLOYMENT_READINESS_AUDIT.md's P2 backlog) is.
SIMULTANEOUS_UPLOADS_COVERED = 6

_API_BLOCK = re.compile(r"^\s*location\s+/api/\s*\{(.*?)^\s*\}", re.DOTALL | re.MULTILINE)
_DURATION = re.compile(r"^(\d+)(ms|[smhdwMy])?$")


def _parse_duration_seconds(value: str) -> float:
    """nginx time values carry a unit suffix and default to seconds when
    bare (`600` and `600s` are identical). Only the units plausible for a
    proxy timeout are handled; anything else fails loudly rather than being
    silently misread as seconds.
    """
    m = _DURATION.match(value.strip())
    assert m, f"unparseable nginx time value {value!r} in {NGINX_CONF}"
    amount, unit = int(m.group(1)), m.group(2) or "s"
    factors = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400}
    assert unit in factors, f"unexpected nginx time unit {unit!r} in {value!r}"
    return amount * factors[unit]


def _api_location_block() -> str:
    body = _API_BLOCK.search(NGINX_CONF.read_text(encoding="utf-8"))
    assert body, f"no `location /api/ {{ ... }}` block found in {NGINX_CONF}"
    return body.group(1)


def _directive_seconds(block: str, name: str) -> float:
    m = re.search(rf"^\s*{name}\s+(\S+?);", block, re.MULTILINE)
    assert m, (
        f"`location /api/` in {NGINX_CONF} sets no {name}, so it inherits nginx's "
        f"default of 60s. /api/transcribe* awaits Soniox synchronously inside the "
        f"request and can legitimately run far longer than that; without an explicit "
        f"value the edge 504s while the backend completes and persists the recording."
    )
    return _parse_duration_seconds(m.group(1))


def _max_single_request_seconds() -> int:
    """Worst-case wall-clock for one /api/transcribe* request that already
    holds an upload worker: every Soniox hop transcribe_file can make, in
    series. BATCH_POLL_TIMEOUT alone is not the budget - its clock starts
    only after the file upload and job creation, and the transcript fetch
    plus the cleanup in transcribe_file's `finally` run after it.
    """
    return (
        sx.UPLOAD_TIMEOUT               # POST /v1/files
        + sx.TRANSCRIPTION_INIT_TIMEOUT  # POST /v1/transcriptions
        + sx.BATCH_POLL_TIMEOUT          # the poll loop
        + sx.POLL_REQUEST_TIMEOUT        # GET .../transcript
        # cleanup_remote_resources in the `finally`: DELETE transcription,
        # its POST /cancel fallback, then DELETE the file.
        + 3 * sx.POLL_REQUEST_TIMEOUT
    )


def _required_nginx_seconds() -> int:
    service = _max_single_request_seconds()
    queued_rounds = -(-(SIMULTANEOUS_UPLOADS_COVERED - UPLOAD_POOL_WORKERS) // UPLOAD_POOL_WORKERS)
    return service * (1 + queued_rounds)


def test_api_read_timeout_exceeds_max_upload_request_time():
    actual = _directive_seconds(_api_location_block(), "proxy_read_timeout")
    required = _required_nginx_seconds()
    assert actual >= required, (
        "INVARIANT: nginx's /api/ proxy_read_timeout must always exceed the maximum "
        "wall-clock time a single /api/transcribe* request can legitimately consume, "
        "so the application's own timeout is what rejects a slow upload - never the "
        "edge. Otherwise nginx returns a 504 while the backend runs to completion and "
        "persists the recording, and the user re-uploads a file that already "
        f"succeeded.\n"
        f"  nginx.conf `location /api/` proxy_read_timeout: {actual:g}s\n"
        f"  required: {required}s = {_max_single_request_seconds()}s per request "
        f"(BATCH_POLL_TIMEOUT {sx.BATCH_POLL_TIMEOUT}s + the Soniox hops around it) "
        f"x {SIMULTANEOUS_UPLOADS_COVERED} simultaneous uploads queued on "
        f"_UPLOAD_EXECUTOR's {UPLOAD_POOL_WORKERS} workers.\n"
        "Raise proxy_read_timeout in frontend/nginx.conf to match, or lower "
        "BATCH_POLL_TIMEOUT - but change both together, never one alone."
    )


def test_api_send_timeout_also_set():
    """proxy_send_timeout defaults to 60s too, and governs writing the
    request body upstream - a 25MB upload (client_max_body_size) over a slow
    link hits it before transcription has even started.
    """
    actual = _directive_seconds(_api_location_block(), "proxy_send_timeout")
    assert actual >= _required_nginx_seconds()


def test_batch_poll_timeout_is_a_waitable_duration():
    """Half of the invariant above, and the half a user actually feels: this
    is how long a browser sits on a spinner before the app gives up. Kept a
    module constant (not env-configurable) precisely so this bound is
    enforceable at test time - see the comment on it in soniox_client.py.
    """
    assert 120 <= sx.BATCH_POLL_TIMEOUT <= 180, (
        f"BATCH_POLL_TIMEOUT is {sx.BATCH_POLL_TIMEOUT}s. It is synchronous request "
        "wall-clock, not background work, so it must stay inside a duration a user "
        "will realistically wait through (120-180s). Anything longer needs the async "
        "job API, not a bigger timeout."
    )
