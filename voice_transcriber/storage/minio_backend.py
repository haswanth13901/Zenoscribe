"""MinIO (S3-compatible) storage backend - STORAGE_BACKEND=minio, what
production uses. The `minio` SDK's exceptions are translated to
StorageNotFound at this module's boundary so nothing above it needs to know
S3 error codes exist.
"""

import io
from pathlib import Path
from typing import BinaryIO, Iterator

from minio import Minio
from minio.error import S3Error

try:
    from .. import config
    from .base import StorageNotFound
except ImportError:  # run flat from inside the package dir
    import config
    from storage.base import StorageNotFound

_client: Minio = None


def _get_client() -> Minio:
    """Lazy singleton, mirroring db.py's _get_pool() pattern. Bucket
    creation is idempotent (checked every time a fresh client is built,
    not on every call) so a first-boot-against-an-empty-MinIO deployment
    doesn't need a separate manual provisioning step."""
    global _client
    if _client is None:
        _client = Minio(
            config.MINIO_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
            secure=config.MINIO_SECURE,
        )
        if not _client.bucket_exists(config.MINIO_BUCKET):
            _client.make_bucket(config.MINIO_BUCKET)
    return _client


def close_client():
    """Test/shutdown hook, mirroring db.close_pool()."""
    global _client
    _client = None


def _is_not_found(exc: S3Error) -> bool:
    return exc.code in ("NoSuchKey", "NoSuchObject")


class _MinioObjectStream:
    """Adapts minio's underlying urllib3 response to a plain read()/close()
    object, so routers/recordings.py's chunked-read loop works identically
    whether
    the backend handed it this or a local `open(path, "rb")` file object."""

    def __init__(self, response):
        self._response = response

    def read(self, size: int = -1) -> bytes:
        amt = None if size is None or size < 0 else size
        return self._response.read(amt)

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            self._response.release_conn()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


class MinioStorageService:
    def upload(self, key: str, local_path: Path, content_type: str) -> None:
        client = _get_client()
        client.fput_object(config.MINIO_BUCKET, key, str(local_path), content_type=content_type)
        local_path.unlink(missing_ok=True)

    def download_to(self, key: str, local_path: Path) -> None:
        client = _get_client()
        local_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            client.fget_object(config.MINIO_BUCKET, key, str(local_path))
        except S3Error as exc:
            if _is_not_found(exc):
                raise StorageNotFound(key) from exc
            raise

    def open_stream(self, key: str) -> BinaryIO:
        client = _get_client()
        try:
            response = client.get_object(config.MINIO_BUCKET, key)
        except S3Error as exc:
            if _is_not_found(exc):
                raise StorageNotFound(key) from exc
            raise
        return _MinioObjectStream(response)

    def get_text(self, key: str) -> str:
        with self.open_stream(key) as stream:
            return stream.read().decode("utf-8")

    def upload_text(self, key: str, text: str, content_type: str = "text/plain") -> None:
        data = text.encode("utf-8")
        client = _get_client()
        client.put_object(
            config.MINIO_BUCKET, key, io.BytesIO(data), length=len(data),
            content_type=content_type,
        )

    def delete(self, key: str) -> None:
        client = _get_client()
        try:
            client.remove_object(config.MINIO_BUCKET, key)
        except S3Error as exc:
            if not _is_not_found(exc):
                raise

    def exists(self, key: str) -> bool:
        client = _get_client()
        try:
            client.stat_object(config.MINIO_BUCKET, key)
            return True
        except S3Error as exc:
            if _is_not_found(exc):
                return False
            raise

    def list_keys(self, prefix: str = "users") -> Iterator[str]:
        client = _get_client()
        for obj in client.list_objects(config.MINIO_BUCKET, prefix=prefix, recursive=True):
            yield obj.object_name
