"""Unit tests for voice_transcriber.storage.

LocalStorageService is tested against a real filesystem (tmp_path) - it's a
genuine implementation, not a fake, so this is real coverage of the
interface contract. MinioStorageService is tested against a mocked `minio`
client instead: there is no MinIO server available in this environment, so
these tests verify the adapter's own logic (key/bucket/content-type
plumbing, S3Error -> StorageNotFound translation) rather than end-to-end
behavior against a real store. Real MinIO integration is UNVERIFIED here -
see SCALABILITY_AUDIT.md/HORIZONTAL_SCALABILITY_READINESS.md.
"""
from unittest.mock import MagicMock

import pytest
from minio.error import S3Error

from voice_transcriber import config
from voice_transcriber.storage import StorageNotFound, get_storage, recording_key
from voice_transcriber.storage.local import LocalStorageService
from voice_transcriber.storage.minio_backend import MinioStorageService


def test_recording_key_shape():
    assert recording_key("u1", "rec-1", ".wav") == "users/u1/recordings/rec-1.wav"


@pytest.mark.parametrize("bad_user_id,bad_recording_id", [
    ("../../etc", "rec-1"),
    ("u1", "../../etc/passwd"),
    ("u1", "a/b"),
    ("u1", "a\\b"),
    ("u1", "a..b"),
])
def test_recording_key_rejects_path_traversal_components(bad_user_id, bad_recording_id):
    with pytest.raises(ValueError):
        recording_key(bad_user_id, bad_recording_id, ".wav")


def test_get_storage_returns_local_by_default(monkeypatch):
    monkeypatch.setattr(config, "STORAGE_BACKEND", "local")
    assert isinstance(get_storage(), LocalStorageService)


def test_get_storage_rejects_unknown_backend(monkeypatch):
    monkeypatch.setattr(config, "STORAGE_BACKEND", "sftp")
    with pytest.raises(RuntimeError):
        get_storage()


# ---- LocalStorageService: real filesystem ----

@pytest.fixture
def local_store(isolated_recordings):
    return LocalStorageService()


def test_local_upload_then_download_roundtrips_bytes(local_store, tmp_path):
    src = tmp_path / "in.wav"
    src.write_bytes(b"RIFF....fake wav bytes")
    key = recording_key("u1", "r1", ".wav")

    local_store.upload(key, src, "audio/wav")

    assert not src.exists()  # consumed
    assert local_store.exists(key)
    out = tmp_path / "out.wav"
    local_store.download_to(key, out)
    assert out.read_bytes() == b"RIFF....fake wav bytes"


def test_local_open_stream_reads_full_content(local_store, tmp_path):
    src = tmp_path / "in.wav"
    src.write_bytes(b"abc123")
    key = recording_key("u1", "r2", ".wav")
    local_store.upload(key, src, "audio/wav")

    with local_store.open_stream(key) as stream:
        assert stream.read() == b"abc123"


def test_local_upload_text_and_get_text_roundtrip(local_store):
    key = recording_key("u1", "r3", ".txt")
    local_store.upload_text(key, "hello transcript")
    assert local_store.get_text(key) == "hello transcript"


def test_local_missing_key_raises_storage_not_found(local_store):
    key = recording_key("u1", "missing", ".wav")
    with pytest.raises(StorageNotFound):
        local_store.download_to(key, config.RECORDINGS / "out.wav")
    with pytest.raises(StorageNotFound):
        local_store.open_stream(key)
    with pytest.raises(StorageNotFound):
        local_store.get_text(key)
    assert local_store.exists(key) is False


def test_local_delete_is_idempotent_on_missing_key(local_store):
    key = recording_key("u1", "never-existed", ".wav")
    local_store.delete(key)  # must not raise
    local_store.delete(key)


def test_local_list_keys_returns_only_users_prefix_not_live_scratch(local_store, tmp_path):
    src1 = tmp_path / "a.wav"
    src1.write_bytes(b"a")
    src2 = tmp_path / "b.wav"
    src2.write_bytes(b"b")
    local_store.upload(recording_key("u1", "r1", ".wav"), src1, "audio/wav")
    local_store.upload(recording_key("u2", "r2", ".wav"), src2, "audio/wav")
    # A live-session scratch file sitting alongside, under _live/ - not a
    # real object, must never show up in list_keys()'s default listing.
    scratch = config.live_scratch_dir() / "in-progress.wav"
    scratch.write_bytes(b"scratch")

    keys = set(local_store.list_keys())
    assert keys == {
        recording_key("u1", "r1", ".wav"),
        recording_key("u2", "r2", ".wav"),
    }


def test_local_delete_removes_existing_object(local_store, tmp_path):
    src = tmp_path / "in.wav"
    src.write_bytes(b"data")
    key = recording_key("u1", "r4", ".wav")
    local_store.upload(key, src, "audio/wav")
    assert local_store.exists(key)

    local_store.delete(key)
    assert not local_store.exists(key)


# ---- MinioStorageService: mocked minio.Minio client ----

@pytest.fixture
def minio_store(monkeypatch):
    """A MinioStorageService whose underlying client is a MagicMock, so
    these tests exercise this module's own logic without a real server."""
    import voice_transcriber.storage.minio_backend as backend
    mock_client = MagicMock()
    mock_client.bucket_exists.return_value = True
    monkeypatch.setattr(backend, "_client", mock_client)
    yield MinioStorageService(), mock_client
    monkeypatch.setattr(backend, "_client", None)


def _s3_not_found():
    return S3Error(
        code="NoSuchKey", message="not found", resource="/x", request_id="1",
        host_id="h", response=MagicMock(),
    )


def test_minio_upload_calls_fput_object_with_bucket_key_and_content_type(minio_store, tmp_path):
    store, mock_client = minio_store
    src = tmp_path / "in.wav"
    src.write_bytes(b"data")
    key = recording_key("u1", "r1", ".wav")

    store.upload(key, src, "audio/wav")

    mock_client.fput_object.assert_called_once_with(
        config.MINIO_BUCKET, key, str(src), content_type="audio/wav",
    )
    assert not src.exists()  # consumed on success


def test_minio_download_translates_not_found(minio_store, tmp_path):
    store, mock_client = minio_store
    mock_client.fget_object.side_effect = _s3_not_found()

    with pytest.raises(StorageNotFound):
        store.download_to("users/u1/recordings/missing.wav", tmp_path / "out.wav")


def test_minio_open_stream_translates_not_found(minio_store):
    store, mock_client = minio_store
    mock_client.get_object.side_effect = _s3_not_found()

    with pytest.raises(StorageNotFound):
        store.open_stream("users/u1/recordings/missing.wav")


def test_minio_open_stream_wraps_response_read_and_close(minio_store):
    store, mock_client = minio_store
    fake_response = MagicMock()
    fake_response.read.return_value = b"chunk"
    mock_client.get_object.return_value = fake_response

    stream = store.open_stream("users/u1/recordings/r1.wav")
    assert stream.read() == b"chunk"
    stream.close()
    fake_response.close.assert_called_once()
    fake_response.release_conn.assert_called_once()


def test_minio_delete_is_idempotent_on_not_found(minio_store):
    store, mock_client = minio_store
    mock_client.remove_object.side_effect = _s3_not_found()
    store.delete("users/u1/recordings/missing.wav")  # must not raise


def test_minio_delete_reraises_non_not_found_errors(minio_store):
    store, mock_client = minio_store
    mock_client.remove_object.side_effect = S3Error(
        code="AccessDenied", message="nope", resource="/x", request_id="1",
        host_id="h", response=MagicMock(),
    )
    with pytest.raises(S3Error):
        store.delete("users/u1/recordings/r1.wav")


def test_minio_exists_true_and_false(minio_store):
    store, mock_client = minio_store
    mock_client.stat_object.return_value = MagicMock()
    assert store.exists("users/u1/recordings/r1.wav") is True

    mock_client.stat_object.side_effect = _s3_not_found()
    assert store.exists("users/u1/recordings/r1.wav") is False


def test_minio_list_keys_yields_object_names(minio_store):
    store, mock_client = minio_store
    obj_a = MagicMock()
    obj_a.object_name = "users/u1/recordings/r1.wav"
    obj_b = MagicMock()
    obj_b.object_name = "users/u1/recordings/r1.txt"
    mock_client.list_objects.return_value = [obj_a, obj_b]

    keys = list(store.list_keys())

    mock_client.list_objects.assert_called_once_with(
        config.MINIO_BUCKET, prefix="users", recursive=True,
    )
    assert keys == ["users/u1/recordings/r1.wav", "users/u1/recordings/r1.txt"]


def test_minio_upload_text_puts_encoded_bytes_with_length(minio_store):
    store, mock_client = minio_store
    store.upload_text("users/u1/recordings/r1.txt", "hello")

    args, kwargs = mock_client.put_object.call_args
    assert args[0] == config.MINIO_BUCKET
    assert args[1] == "users/u1/recordings/r1.txt"
    assert kwargs["length"] == len("hello".encode("utf-8"))
    assert kwargs["content_type"] == "text/plain"
