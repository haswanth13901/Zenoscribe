"""_persist_upload_recording (defined in routers/uploads.py, reached here
via routes_api's re-export): the WAV/transcript/DB-row
persistence that a successful /api/transcribe or /api/transcribe/translate
call now runs, plus end-to-end coverage through both routes.

Before this, both batch-upload endpoints discarded the uploaded audio and
the transcript once the response was sent - nothing ever showed up in
My/All Recordings for uploads, unlike the live Recorder/Translate sessions.
"""
import logging
from pathlib import Path

import pytest

from voice_transcriber import config, db, routes_api


def _login(client, username, password):
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _sample_turns():
    return [
        {"speaker": "user-1", "text": "Hello", "start": 0.0, "end": 1.0},
        {"speaker": "user-2", "text": "world", "start": 1.0, "end": 2.0},
    ]


def _sample_translated_turns():
    return [
        {"speaker": "user-1", "text": "Hola", "translation": "Hello", "start": 0.0, "end": 1.0},
    ]


@pytest.fixture
def upload_user(make_user):
    user_id = make_user("upload_user", "UploadPass123!")
    return {"id": user_id, "username": "upload_user"}


def test_persist_writes_audio_txt_and_db_row(isolated_db, isolated_recordings, upload_user, make_wav):
    tmp_path = make_wav(isolated_recordings / "incoming.wav")
    turns = _sample_turns()

    moved = routes_api._persist_upload_recording(upload_user, str(tmp_path), ".wav", turns)

    assert moved is True
    assert not tmp_path.exists()  # moved, not copied
    audio_files = list(isolated_recordings.glob("**/*.wav"))
    assert len(audio_files) == 1

    rows = db.list_recordings(user_id=upload_user["id"])
    assert len(rows) == 1
    assert rows[0]["source"] == "upload"
    assert rows[0]["turn_count"] == 2
    assert rows[0]["preview"] == "Hello world"

    txt_path = config.RECORDINGS / rows[0]["txt_file"]
    assert txt_path.exists()
    assert "Hello" in txt_path.read_text(encoding="utf-8")


def test_persist_includes_translation_in_transcript_and_preview(
    isolated_db, isolated_recordings, upload_user, make_wav,
):
    tmp_path = make_wav(isolated_recordings / "incoming.wav")
    turns = _sample_translated_turns()

    routes_api._persist_upload_recording(upload_user, str(tmp_path), ".wav", turns)

    rows = db.list_recordings(user_id=upload_user["id"])
    assert rows[0]["preview"] == "Hello"  # favors translation, like translate.py's live sessions

    txt_path = config.RECORDINGS / rows[0]["txt_file"]
    text = txt_path.read_text(encoding="utf-8")
    assert "Hola" in text and "-> Hello" in text


def test_persist_non_wav_suffix_skips_duration_but_still_saves(
    isolated_db, isolated_recordings, upload_user, tmp_path,
):
    fake_mp3 = tmp_path / "incoming.mp3"
    fake_mp3.write_bytes(b"not a real mp3, just needs to exist")

    moved = routes_api._persist_upload_recording(upload_user, str(fake_mp3), ".mp3", _sample_turns())

    assert moved is True
    rows = db.list_recordings(user_id=upload_user["id"])
    assert rows[0]["duration"] == 0.0
    assert Path(rows[0]["wav_file"]).suffix == ".mp3"


def test_persist_empty_turns_does_not_move_or_save(isolated_db, isolated_recordings, upload_user, make_wav):
    tmp_path = make_wav(isolated_recordings / "incoming.wav")

    moved = routes_api._persist_upload_recording(upload_user, str(tmp_path), ".wav", [])

    assert moved is False
    assert tmp_path.exists()
    assert db.list_recordings(user_id=upload_user["id"]) == []


def test_db_failure_still_moves_audio_and_writes_transcript(
    isolated_db, isolated_recordings, upload_user, make_wav, monkeypatch, caplog,
):
    tmp_path = make_wav(isolated_recordings / "incoming.wav")

    def _raise(*a, **kw):
        raise RuntimeError("simulated db failure")

    monkeypatch.setattr(db, "add_recording", _raise)

    with caplog.at_level(logging.ERROR, logger="api"):
        moved = routes_api._persist_upload_recording(upload_user, str(tmp_path), ".wav", _sample_turns())

    assert moved is True
    assert not tmp_path.exists()
    assert list(isolated_recordings.glob("**/*.txt"))
    assert db.list_recordings(user_id=upload_user["id"]) == []
    assert any("could not register upload recording" in r.message for r in caplog.records)


def test_transcribe_endpoint_persists_recording(client, make_user, make_wav, monkeypatch):
    monkeypatch.setattr(
        routes_api.sx, "transcribe_file", lambda path, *a, **kw: _sample_turns(),
    )
    make_user("plain_upload_user", "PlainUploadPass123!")
    headers = _login(client, "plain_upload_user", "PlainUploadPass123!")

    r = client.post("/api/transcribe", headers=headers,
                    files={"file": ("test.wav", make_wav(), "audio/wav")})
    assert r.status_code == 200

    r = client.get("/api/recordings", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["source"] == "upload"
    assert rows[0]["turn_count"] == 2


def test_transcribe_translate_endpoint_persists_recording(client, make_user, make_wav, monkeypatch):
    monkeypatch.setattr(
        routes_api.sx, "transcribe_file", lambda path, *a, **kw: _sample_translated_turns(),
    )
    make_user("translate_upload_user", "TranslateUploadPass123!")
    headers = _login(client, "translate_upload_user", "TranslateUploadPass123!")

    r = client.post("/api/transcribe/translate?target_language=en", headers=headers,
                    files={"file": ("test.wav", make_wav(), "audio/wav")})
    assert r.status_code == 200

    r = client.get("/api/recordings", headers=headers)
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["source"] == "upload"

    r2 = client.get(f"/api/recordings/{rows[0]['id']}/audio", headers=headers)
    assert r2.status_code == 200
    assert r2.headers["content-type"].startswith("audio")
