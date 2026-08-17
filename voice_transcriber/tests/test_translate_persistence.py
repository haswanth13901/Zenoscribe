"""_save_translate_session: the three-way WAV/transcript/DB-row persistence
that runs when a live Translate session ends.

Exercised directly rather than through the /ws/translate socket - that path
needs a real Soniox connection with no fake-mode hook (unlike transcribe.py's
transcribe_file, translate.py has nothing analogous), so it's only reachable
end-to-end with real credentials. _save_translate_session is the extracted,
directly-callable persistence step translate.py's websocket handler calls
in its `finally` block once a session has at least one turn.
"""
import datetime
import logging
from pathlib import Path

import pytest

from voice_transcriber import config, db, translate

STARTED_AT = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _sample_turns():
    return [
        {"start": 0.0, "speaker": "user-1", "language": "es",
         "source": "Hola", "translation": "Hello"},
        {"start": 3.0, "speaker": "user-1", "language": "es",
         "source": "Adios", "translation": "Goodbye"},
    ]


@pytest.fixture
def ws_user(make_user):
    user_id = make_user("translate_user", "TranslatePass123!")
    return {"id": user_id, "username": "translate_user"}


@pytest.fixture
def session_wav(isolated_recordings, make_wav):
    session = "20260101-000000-translate_user-translate-abc123"
    wav_path = make_wav(isolated_recordings / f"{session}.wav")
    return session, wav_path


async def test_save_translate_session_writes_wav_txt_and_db_row(
    isolated_db, isolated_recordings, ws_user, session_wav,
):
    session, wav_path = session_wav
    turns = _sample_turns()

    await translate._save_translate_session(session, ws_user, wav_path, STARTED_AT, turns)

    txt_path = config.RECORDINGS / f"{session}.txt"
    assert txt_path.exists()
    text = txt_path.read_text(encoding="utf-8")
    assert "Hola" in text and "Hello" in text

    row = db.get_recording(session)
    assert row is not None
    assert row["source"] == "translate"
    assert row["turn_count"] == 2
    assert row["preview"] == "Hello Goodbye"


async def test_db_failure_still_writes_transcript_and_logs_distinctly(
    isolated_db, isolated_recordings, ws_user, session_wav, monkeypatch, caplog,
):
    session, wav_path = session_wav
    turns = _sample_turns()

    def _raise(*a, **kw):
        raise RuntimeError("simulated db failure")

    monkeypatch.setattr(db, "add_recording", _raise)

    with caplog.at_level(logging.ERROR, logger="translate"):
        await translate._save_translate_session(session, ws_user, wav_path, STARTED_AT, turns)

    txt_path = config.RECORDINGS / f"{session}.txt"
    assert txt_path.exists()
    assert "Hola" in txt_path.read_text(encoding="utf-8")
    assert db.get_recording(session) is None

    messages = [r.message for r in caplog.records]
    assert any("could not register translate recording" in m for m in messages)
    assert not any("failed to write translate transcript" in m for m in messages)


async def test_transcript_failure_still_writes_db_row_and_logs_distinctly(
    isolated_db, isolated_recordings, ws_user, session_wav, monkeypatch, caplog,
):
    session, wav_path = session_wav
    turns = _sample_turns()

    def _raise(self, *a, **kw):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(Path, "write_text", _raise)

    with caplog.at_level(logging.ERROR, logger="translate"):
        await translate._save_translate_session(session, ws_user, wav_path, STARTED_AT, turns)

    row = db.get_recording(session)
    assert row is not None
    assert row["source"] == "translate"
    assert row["turn_count"] == 2

    messages = [r.message for r in caplog.records]
    assert any("failed to write translate transcript" in m for m in messages)
    assert not any("could not register translate recording" in m for m in messages)


async def test_wav_duration_failure_falls_back_to_zero_and_still_saves(
    isolated_db, isolated_recordings, ws_user, session_wav, monkeypatch, caplog,
):
    session, wav_path = session_wav
    turns = _sample_turns()

    def _raise(path):
        raise OSError("simulated corrupt wav")

    monkeypatch.setattr(translate, "_wav_duration", _raise)

    with caplog.at_level(logging.ERROR, logger="translate"):
        await translate._save_translate_session(session, ws_user, wav_path, STARTED_AT, turns)

    row = db.get_recording(session)
    assert row is not None
    assert row["duration"] == 0.0

    messages = [r.message for r in caplog.records]
    assert any("failed to read translate wav duration" in m for m in messages)
