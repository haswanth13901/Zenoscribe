"""_save_transcribe_session: the audio-upload/transcript-upload/DB-row
persistence that runs when a live Recorder (transcribe.py) session ends.

Exercised directly rather than through the /ws socket - that path needs a
real Soniox connection with no fake-mode hook (unlike soniox_client's
transcribe_file, transcribe.py's live streaming path has nothing
analogous), so it's only reachable end-to-end with real credentials.
_save_transcribe_session is the extracted, directly-callable persistence
step transcribe.py's websocket handler calls in its `finally` block once a
session has at least one turn - mirrors translate.py's
_save_translate_session and its test coverage in test_translate_persistence.py.
"""
import datetime
import logging
from pathlib import Path

import pytest

from voice_transcriber import config, db, storage, transcribe

STARTED_AT = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _sample_turns():
    return [
        {"speaker": "user-1", "start": 0.0, "text": "Hello"},
        {"speaker": "user-2", "start": 3.0, "text": "world"},
    ]


@pytest.fixture
def rec_user(make_user):
    user_id = make_user("transcribe_user", "TranscribePass123!")
    return user_id, "transcribe_user"


@pytest.fixture
def session_wav(isolated_recordings, make_wav):
    session = "20260101-000000-transcribe_user-abc123"
    wav_path = make_wav(isolated_recordings / f"{session}.wav")
    return session, wav_path


async def test_save_transcribe_session_uploads_audio_txt_and_db_row(
    isolated_db, isolated_recordings, rec_user, session_wav,
):
    user_id, username = rec_user
    session, wav_path = session_wav
    turns = _sample_turns()

    await transcribe._save_transcribe_session(session, user_id, username, wav_path, STARTED_AT, turns)

    row = db.get_recording(session)
    assert row is not None
    assert row["source"] == "transcribe"
    assert row["turn_count"] == 2
    assert row["preview"] == "Hello world"

    txt_key = storage.recording_key(user_id, session, ".txt")
    wav_key = storage.recording_key(user_id, session, ".wav")
    assert row["txt_file"] == txt_key
    assert row["wav_file"] == wav_key

    txt_path = config.RECORDINGS / txt_key
    assert txt_path.exists()
    assert "Hello" in txt_path.read_text(encoding="utf-8")

    wav_dest = config.RECORDINGS / wav_key
    assert wav_dest.exists()
    assert not wav_path.exists()  # consumed by storage.upload()


async def test_db_failure_still_uploads_audio_and_transcript(
    isolated_db, isolated_recordings, rec_user, session_wav, monkeypatch, caplog,
):
    user_id, username = rec_user
    session, wav_path = session_wav
    turns = _sample_turns()

    def _raise(*a, **kw):
        raise RuntimeError("simulated db failure")

    monkeypatch.setattr(db, "add_recording", _raise)

    with caplog.at_level(logging.ERROR, logger="transcribe"):
        await transcribe._save_transcribe_session(session, user_id, username, wav_path, STARTED_AT, turns)

    txt_key = storage.recording_key(user_id, session, ".txt")
    wav_key = storage.recording_key(user_id, session, ".wav")
    assert (config.RECORDINGS / txt_key).exists()
    assert (config.RECORDINGS / wav_key).exists()
    assert db.get_recording(session) is None
    assert any("could not register recording" in r.message for r in caplog.records)


async def test_transcript_upload_failure_still_writes_db_row_and_logs_distinctly(
    isolated_db, isolated_recordings, rec_user, session_wav, monkeypatch, caplog,
):
    user_id, username = rec_user
    session, wav_path = session_wav
    turns = _sample_turns()

    def _raise(self, *a, **kw):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(Path, "write_text", _raise)

    with caplog.at_level(logging.ERROR, logger="transcribe"):
        await transcribe._save_transcribe_session(session, user_id, username, wav_path, STARTED_AT, turns)

    row = db.get_recording(session)
    assert row is not None
    assert row["source"] == "transcribe"
    assert row["turn_count"] == 2

    messages = [r.message for r in caplog.records]
    assert any("failed to store transcript" in m for m in messages)
    assert not any("could not register recording" in m for m in messages)


async def test_wav_duration_failure_falls_back_to_zero_and_still_saves(
    isolated_db, isolated_recordings, rec_user, session_wav, monkeypatch, caplog,
):
    user_id, username = rec_user
    session, wav_path = session_wav
    turns = _sample_turns()

    def _raise(path):
        raise OSError("simulated corrupt wav")

    monkeypatch.setattr(transcribe, "_wav_duration", _raise)

    with caplog.at_level(logging.ERROR, logger="transcribe"):
        await transcribe._save_transcribe_session(session, user_id, username, wav_path, STARTED_AT, turns)

    row = db.get_recording(session)
    assert row is not None
    assert row["duration"] == 0.0

    messages = [r.message for r in caplog.records]
    assert any("failed to read wav duration" in m for m in messages)


async def test_audio_upload_failure_still_writes_transcript_and_db_row(
    isolated_db, isolated_recordings, rec_user, session_wav, monkeypatch, caplog,
):
    """The DB row still gets created pointing at a wav_key even if the
    upload itself failed - same accepted drift-tolerant philosophy as
    translate.py/routers/uploads.py's other independent-step persistence
    (reconcile_recordings.py exists precisely to find/report this class of
    mismatch, not to make it impossible)."""
    user_id, username = rec_user
    session, wav_path = session_wav
    turns = _sample_turns()

    def _raise(*a, **kw):
        raise RuntimeError("simulated storage outage")

    monkeypatch.setattr(storage.LocalStorageService, "upload", _raise)

    with caplog.at_level(logging.ERROR, logger="transcribe"):
        await transcribe._save_transcribe_session(session, user_id, username, wav_path, STARTED_AT, turns)

    row = db.get_recording(session)
    assert row is not None
    assert row["wav_file"] == storage.recording_key(user_id, session, ".wav")

    txt_key = storage.recording_key(user_id, session, ".txt")
    assert (config.RECORDINGS / txt_key).exists()

    messages = [r.message for r in caplog.records]
    assert any("failed to store recording audio" in m for m in messages)
