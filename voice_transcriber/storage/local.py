"""Local-filesystem storage backend - STORAGE_BACKEND=local (dev/test
default). Root directory is read fresh from config.RECORDINGS on every call,
not captured at construction, so tests can keep monkeypatching
config.RECORDINGS the same way they always have (see conftest.py's
isolated_recordings fixture) and see it take effect immediately.
"""

import shutil
from pathlib import Path
from typing import BinaryIO, Iterator

try:
    from .. import config
    from .base import StorageNotFound
except ImportError:  # run flat from inside the package dir
    import config
    from storage.base import StorageNotFound


class LocalStorageService:
    def _path_for(self, key: str) -> Path:
        # Keys are always forward-slash relative paths (see base.recording_key) -
        # Path() handles that correctly on Windows and POSIX alike.
        return config.RECORDINGS / key

    def upload(self, key: str, local_path: Path, content_type: str) -> None:
        dest = self._path_for(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # shutil.move handles the common case (same filesystem - a cheap
        # rename) and falls back to copy+delete across filesystems/drives,
        # matching what routes_api.py's upload path already relied on before
        # this abstraction existed.
        shutil.move(str(local_path), str(dest))

    def download_to(self, key: str, local_path: Path) -> None:
        src = self._path_for(key)
        if not src.exists():
            raise StorageNotFound(key)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, local_path)

    def open_stream(self, key: str) -> BinaryIO:
        src = self._path_for(key)
        if not src.exists():
            raise StorageNotFound(key)
        return open(src, "rb")

    def get_text(self, key: str) -> str:
        src = self._path_for(key)
        if not src.exists():
            raise StorageNotFound(key)
        return src.read_text(encoding="utf-8")

    def upload_text(self, key: str, text: str, content_type: str = "text/plain") -> None:
        dest = self._path_for(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")

    def delete(self, key: str) -> None:
        self._path_for(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path_for(key).exists()

    def list_keys(self, prefix: str = "users") -> Iterator[str]:
        # Defaults to "users" (every real recording_key() lives under
        # users/...), NOT the bare RECORDINGS root - that would also walk
        # config.live_scratch_dir()'s "_live/" subtree, which holds
        # in-progress live-session scratch files that were deliberately
        # never uploaded through this interface and aren't real objects.
        root = self._path_for(prefix)
        if not root.exists():
            return
        base = config.RECORDINGS
        for path in root.rglob("*"):
            if path.is_file():
                yield path.relative_to(base).as_posix()
