"""Storage backend interface.

Every recording (WAV audio + text transcript) is addressed by an opaque
string key - callers never construct filesystem paths or bucket URLs
themselves. `recording_key()` below is the one place that decides what a
key looks like; both backends (local.py, minio_backend.py) just have to
honor whatever string they're given.
"""

from pathlib import Path
from typing import BinaryIO, Iterator, Protocol


def recording_key(user_id: str, recording_id: str, suffix: str) -> str:
    """The one key scheme used by both backends, so a recording written
    under STORAGE_BACKEND=local and later served under STORAGE_BACKEND=minio
    (or vice versa) resolves to the same logical location. `suffix` includes
    the dot (e.g. ".wav", ".txt", or the original upload extension).

    `user_id` is always server-generated (uuid.uuid4().hex, db.create_user)
    and never attacker-influenceable. `recording_id` (a "session" string in
    transcribe.py/translate.py/routers/uploads.py) embeds the acting user's
    username, which the real primary guard against this lives in
    routers/admin.py's USERNAME_RE - this check is a second,
    defense-in-depth
    layer here at the one chokepoint every caller passes through, not the
    guard itself.
    """
    for part in (user_id, recording_id):
        if "/" in part or "\\" in part or ".." in part:
            raise ValueError(f"unsafe storage key component: {part!r}")
    return f"users/{user_id}/recordings/{recording_id}{suffix}"


class StorageNotFound(Exception):
    """Raised by download_to()/open_stream() when the key doesn't exist.
    Callers translate this into a 404 - never let it become an unhandled
    500, since a missing recording is an expected, routine state (see
    scripts/reconcile_recordings.py for how files/DB rows can drift)."""


class StorageService(Protocol):
    def upload(self, key: str, local_path: Path, content_type: str) -> None:
        """Consumes local_path: uploads its contents to storage under key,
        then removes the local file. Callers must not read local_path again
        after this returns, and don't need to clean it up themselves - on
        success it's already gone (moved, for the local backend; uploaded
        then deleted, for MinIO). On failure (an exception is raised),
        local_path is left in place so the caller's own error-path cleanup
        still works, matching the existing try/finally unlink pattern in
        routers/uploads.py's upload endpoints."""
        ...

    def download_to(self, key: str, local_path: Path) -> None:
        """Fetch the object at key into a local file. Raises StorageNotFound
        if key doesn't exist."""
        ...

    def open_stream(self, key: str) -> BinaryIO:
        """A readable binary stream for key, for StreamingResponse - avoids
        buffering a whole recording into memory or onto local disk just to
        serve one download. Raises StorageNotFound if key doesn't exist."""
        ...

    def get_text(self, key: str) -> str:
        """Convenience for small text objects (transcripts) - read the
        whole thing as UTF-8. Raises StorageNotFound if key doesn't exist."""
        ...

    def upload_text(self, key: str, text: str, content_type: str = "text/plain") -> None:
        """Convenience for small text objects (transcripts) - write text
        directly under key, without requiring a local temp file first."""
        ...

    def delete(self, key: str) -> None:
        """Remove the object at key. Must NOT raise if key doesn't exist -
        every delete call site here already treats "already gone" as a
        success (matches the existing Path.unlink(missing_ok=True) behavior
        this replaces)."""
        ...

    def exists(self, key: str) -> bool:
        ...

    def list_keys(self, prefix: str = "users") -> Iterator[str]:
        """All keys under prefix (default: every real recording key - see
        recording_key() above). Used only by scripts/reconcile_recordings.py
        to find stored files with no matching DB row - not a hot path, fine
        for either backend to implement simply (a full recursive listing)."""
        ...
