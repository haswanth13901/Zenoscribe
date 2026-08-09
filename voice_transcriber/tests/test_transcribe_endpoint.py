"""POST /api/transcribe: upstream fault-mapping and upload-size enforcement.

Ports tc07_api_timeout_api_test.py, tc08_oversize_upload_test.py, and
tc13_transcribe_runtime_error_test.py. Fault injection is via monkeypatching
routes_api.sx.transcribe_file directly - fast, in-process, no server/network.
"""
import tempfile

from voice_transcriber import config, routes_api


def _login(client, username, password):
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _raise_timeout(path, *args, **kwargs):
    raise TimeoutError("simulated upstream timeout")


def _raise_runtime_error(path, *args, **kwargs):
    raise RuntimeError("simulated upstream runtime error")


def test_transcribe_timeout_maps_to_504(client, make_user, make_wav, monkeypatch):
    monkeypatch.setattr(routes_api.sx, "transcribe_file", _raise_timeout)
    make_user("timeout_user", "TimeoutPass123!")
    headers = _login(client, "timeout_user", "TimeoutPass123!")
    r = client.post("/api/transcribe", headers=headers,
                     files={"file": ("test.wav", make_wav(), "audio/wav")})
    assert r.status_code == 504


def test_transcribe_runtime_error_maps_to_502(client, make_user, make_wav, monkeypatch):
    monkeypatch.setattr(routes_api.sx, "transcribe_file", _raise_runtime_error)
    make_user("runtime_user", "RuntimePass123!")
    headers = _login(client, "runtime_user", "RuntimePass123!")
    r = client.post("/api/transcribe", headers=headers,
                     files={"file": ("test.wav", make_wav(), "audio/wav")})
    assert r.status_code == 502


def test_oversize_upload_rejected_with_413_and_temp_file_cleaned_up(
    client, make_user, make_wav, monkeypatch, tmp_path
):
    monkeypatch.setattr(config, "MAX_UPLOAD_SIZE", 1024)  # 1 KB

    # Redirect the server's temp-upload files into a directory we control, so
    # we can assert nothing is left behind after the 413 response.
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    original_ntf = tempfile.NamedTemporaryFile

    def wrapped_ntf(*args, **kwargs):
        return original_ntf(*args, dir=staging_dir, **kwargs)

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", wrapped_ntf)

    make_user("oversize_user", "OversizePass123!")
    headers = _login(client, "oversize_user", "OversizePass123!")
    # ~2KB of WAV data, comfortably over the 1KB limit.
    big_wav = make_wav(num_frames=1100)
    r = client.post("/api/transcribe", headers=headers,
                     files={"file": ("big.wav", big_wav, "audio/wav")})
    assert r.status_code == 413
    assert list(staging_dir.iterdir()) == []
