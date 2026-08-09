"""Recordings list/transcript/audio access and ownership checks.

Ports the recordings portion of the old full_endpoint_test.py.
"""
import pytest

from voice_transcriber import db


@pytest.fixture
def seeded_recording(isolated_recordings, isolated_db, make_user):
    user_id = make_user("rec_user", "RecPass123!")
    (isolated_recordings / "r.txt").write_text("Hello from test.", encoding="utf-8")
    (isolated_recordings / "r.wav").write_bytes(b"RIFF....WAVEfmt ")
    db.add_recording(
        "rec-1", user_id, "r.wav", "r.txt",
        "2026-01-01T00:00:00", 1.2, 1, "Hello",
    )
    return user_id, "rec-1"


def _login(client, username, password):
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_list_recordings_returns_seeded_entry(client, seeded_recording):
    headers = _login(client, "rec_user", "RecPass123!")
    r = client.get("/api/recordings", headers=headers)
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()}
    assert "rec-1" in ids


def test_get_transcript_returns_text_content(client, seeded_recording):
    _, rec_id = seeded_recording
    headers = _login(client, "rec_user", "RecPass123!")
    r = client.get(f"/api/recordings/{rec_id}/transcript", headers=headers)
    assert r.status_code == 200
    assert r.json()["text"] == "Hello from test."


def test_get_audio_returns_audio_content_type(client, seeded_recording):
    _, rec_id = seeded_recording
    headers = _login(client, "rec_user", "RecPass123!")
    r = client.get(f"/api/recordings/{rec_id}/audio", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio")


def test_user_cannot_access_other_users_recording(client, make_user, seeded_recording):
    _, rec_id = seeded_recording
    make_user("someone_else", "SomeoneElsePass123!")
    headers = _login(client, "someone_else", "SomeoneElsePass123!")
    r = client.get(f"/api/recordings/{rec_id}/transcript", headers=headers)
    assert r.status_code == 404


def test_admin_can_access_any_recording(client, make_user, seeded_recording):
    make_user("rec_admin", "RecAdminPass123!", role="admin")
    headers = _login(client, "rec_admin", "RecAdminPass123!")
    _, rec_id = seeded_recording
    r = client.get(f"/api/recordings/{rec_id}/transcript", headers=headers)
    assert r.status_code == 200
