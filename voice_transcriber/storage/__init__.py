"""Storage backend selection.

Everything outside this package imports from here (`storage.get_storage()`,
`storage.recording_key()`, `storage.StorageNotFound`) and never touches
local.py/minio_backend.py directly, so swapping STORAGE_BACKEND doesn't
require touching call sites.
"""

try:
    from .. import config
    from .base import StorageNotFound, StorageService, recording_key
    from .local import LocalStorageService
except ImportError:  # run flat from inside the package dir
    import config
    from storage.base import StorageNotFound, StorageService, recording_key
    from storage.local import LocalStorageService

__all__ = ["get_storage", "recording_key", "StorageNotFound", "StorageService"]


def get_storage() -> StorageService:
    """Reads config.STORAGE_BACKEND fresh on every call (not cached at
    import time) so tests can monkeypatch it, matching the pattern already
    used for config.DATABASE_URL/config.PRODUCTION elsewhere in this repo.
    The backend implementations themselves each own their own connection
    singleton (db.py's _pool / minio_backend.py's _client equivalent), so
    constructing a new LocalStorageService()/MinioStorageService() here is
    cheap - it holds no state itself."""
    backend = config.STORAGE_BACKEND
    if backend == "local":
        return LocalStorageService()
    if backend == "minio":
        # Imported lazily so the `minio` package (a real runtime dependency,
        # see requirements.txt) is only required when actually selected -
        # STORAGE_BACKEND=local dev/test environments don't need it installed.
        try:
            from .minio_backend import MinioStorageService
        except ImportError:
            from storage.minio_backend import MinioStorageService
        return MinioStorageService()
    raise RuntimeError(f"Unknown STORAGE_BACKEND: {backend!r} (expected 'local' or 'minio')")
