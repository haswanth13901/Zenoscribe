"""Recordings list/transcript/audio access and ownership checks.

Ports the recordings portion of the old full_endpoint_test.py.
"""
import pytest

from voice_transcriber import db, storage
from voice_transcriber.storage.local import LocalStorageService


@pytest.fixture
def seeded_recording(isolated_recordings, isolated_db, make_user):
    user_id = make_user("rec_user", "RecPass123!")
    txt_key = storage.recording_key(user_id, "rec-1", ".txt")
    wav_key = storage.recording_key(user_id, "rec-1", ".wav")
    (isolated_recordings / txt_key).parent.mkdir(parents=True, exist_ok=True)
    (isolated_recordings / txt_key).write_text("Hello from test.", encoding="utf-8")
    (isolated_recordings / wav_key).write_bytes(b"RIFF....WAVEfmt ")
    db.add_recording(
        "rec-1", user_id, wav_key, txt_key,
        "2026-01-01T00:00:00", 1.2, 1, "Hello", "transcribe",
    )
    return user_id, "rec-1"


@pytest.fixture
def mixed_source_recordings(isolated_db, make_user):
    """Two users, each with one transcribe and one translate recording, on
    different dates - enough to exercise source/user/date composing."""
    alice_id = make_user("alice", "AlicePass123!")
    bob_id = make_user("bob", "BobPass123!")
    db.add_recording(
        "alice-transcribe", alice_id, "a1.wav", "a1.txt",
        "2026-01-01T00:00:00", 5.0, 1, "alice recorder", "transcribe",
    )
    db.add_recording(
        "alice-translate", alice_id, "a2.wav", "a2.txt",
        "2026-01-05T00:00:00", 5.0, 1, "alice translate", "translate",
    )
    db.add_recording(
        "bob-transcribe", bob_id, "b1.wav", "b1.txt",
        "2026-01-10T00:00:00", 5.0, 1, "bob recorder", "transcribe",
    )
    return {"alice": alice_id, "bob": bob_id}


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


def test_recording_payload_includes_source(client, seeded_recording):
    headers = _login(client, "rec_user", "RecPass123!")
    r = client.get("/api/recordings", headers=headers)
    row = next(row for row in r.json() if row["id"] == "rec-1")
    assert row["source"] == "transcribe"


def test_own_user_source_filter_excludes_other_users_and_types(
    client, mixed_source_recordings,
):
    """A non-admin's My recordings view: scoped to self
    (routers/recordings.py's
    `scope = ... else user["id"]`) *and* filtered by source, composed.
    alice is already seeded by the mixed_source_recordings fixture."""
    headers = _login(client, "alice", "AlicePass123!")

    r = client.get("/api/recordings", headers=headers, params={"source": "translate"})
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()}
    assert ids == {"alice-translate"}  # not bob's, not alice's transcribe row


def test_admin_source_filter_returns_only_matching_rows(client, make_user, mixed_source_recordings):
    make_user("mix_admin", "MixAdminPass123!", role="admin")
    headers = _login(client, "mix_admin", "MixAdminPass123!")

    r = client.get("/api/recordings", headers=headers, params={"source": "translate"})
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()}
    assert ids == {"alice-translate"}


def test_source_composes_with_user_and_date_filters(client, make_user, mixed_source_recordings):
    make_user("mix_admin2", "MixAdmin2Pass123!", role="admin")
    headers = _login(client, "mix_admin2", "MixAdmin2Pass123!")

    r = client.get(
        "/api/recordings",
        headers=headers,
        params={
            "user_id": mixed_source_recordings["alice"],
            "source": "transcribe",
            "date_from": "2025-12-31",
            "date_to": "2026-01-02",
        },
    )
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()}
    assert ids == {"alice-transcribe"}

    # Same filters but a date range that excludes it -> empty, not an error.
    r = client.get(
        "/api/recordings",
        headers=headers,
        params={
            "user_id": mixed_source_recordings["alice"],
            "source": "transcribe",
            "date_from": "2026-02-01",
        },
    )
    assert r.status_code == 200
    assert r.json() == []


def test_invalid_source_filter_returns_400(client, seeded_recording):
    headers = _login(client, "rec_user", "RecPass123!")
    r = client.get("/api/recordings", headers=headers, params={"source": "bogus"})
    assert r.status_code == 400


def test_invalid_date_filter_returns_400_not_500(client, seeded_recording):
    headers = _login(client, "rec_user", "RecPass123!")
    r = client.get("/api/recordings", headers=headers, params={"date_from": "not-a-date"})
    assert r.status_code == 400


def test_transcript_returns_503_not_500_when_storage_backend_errors(
    client, seeded_recording, monkeypatch,
):
    """Distinct from a missing object (404): the backend itself being
    unreachable (a MinIO outage, a disk error) should read as "try again
    shortly," not silently 500 or incorrectly imply the recording doesn't
    exist."""
    def _raise(self, key):
        raise ConnectionError("simulated storage backend outage")

    monkeypatch.setattr(LocalStorageService, "get_text", _raise)
    _, rec_id = seeded_recording
    headers = _login(client, "rec_user", "RecPass123!")
    r = client.get(f"/api/recordings/{rec_id}/transcript", headers=headers)
    assert r.status_code == 503


def test_audio_returns_503_not_500_when_storage_backend_errors(
    client, seeded_recording, monkeypatch,
):
    def _raise(self, key):
        raise ConnectionError("simulated storage backend outage")

    monkeypatch.setattr(LocalStorageService, "open_stream", _raise)
    _, rec_id = seeded_recording
    headers = _login(client, "rec_user", "RecPass123!")
    r = client.get(f"/api/recordings/{rec_id}/audio", headers=headers)
    assert r.status_code == 503
