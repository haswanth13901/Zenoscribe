"""Tests that make a genuine outbound network call - not part of the default
fast suite (see pytest.ini's `real_network` marker / addopts).

Ports soniox_local_test.py, run_tc07_integration.py, run_transcribe_test.py
(all three duplicated "upload a WAV and see what real/unmocked Soniox does"
at different layers - collapsed here to one direct soniox_client call, which
doesn't need a live server at all) and tc07_transcribe_timeout_test.py.

test_transcribe_file_against_real_soniox spends real Soniox API quota, so it
requires an EXPLICIT opt-in via RUN_REAL_SONIOX_TESTS=true - checking only
for SONIOX_API_KEY is not enough to gate this safely, because
soniox_client.get_api_key() calls load_dotenv() internally, which silently
refills SONIOX_API_KEY from .env even if you unset it at the shell level for
a given run. RUN_REAL_SONIOX_TESTS is a name nothing in the app ever loads
or sets on its own, so it can only become true if a human or CI config
deliberately sets it for that run.
"""
import os

import pytest

from voice_transcriber import soniox_client as sx

pytestmark = pytest.mark.real_network

requires_explicit_opt_in = pytest.mark.skipif(
    os.environ.get("RUN_REAL_SONIOX_TESTS", "").lower() not in ("1", "true", "yes"),
    reason="Set RUN_REAL_SONIOX_TESTS=true to opt in to spending real Soniox API quota",
)
requires_soniox_key = pytest.mark.skipif(
    not os.environ.get("SONIOX_API_KEY"),
    reason="SONIOX_API_KEY not set; skipping real Soniox network test",
)


@requires_explicit_opt_in
@requires_soniox_key
def test_transcribe_file_against_real_soniox(make_wav, tmp_path):
    wav_path = make_wav(path=tmp_path / "real.wav")
    turns = sx.transcribe_file(str(wav_path), poll_interval=1, timeout=60)
    assert isinstance(turns, list)


def test_transcribe_file_network_timeout_against_unroutable_host(make_wav, tmp_path, monkeypatch):
    # No credentials needed - points REST at a non-routable IP to force a
    # genuine network-level timeout/connection failure.
    monkeypatch.setattr(sx, "get_api_key", lambda: "dummykey")
    monkeypatch.setattr(sx, "UPLOAD_TIMEOUT", 3)
    monkeypatch.setattr(sx, "REST", "http://10.255.255.1")

    wav_path = make_wav(path=tmp_path / "unroutable.wav")
    with pytest.raises((TimeoutError, RuntimeError)):
        sx.transcribe_file(str(wav_path), poll_interval=1.0, timeout=5)
