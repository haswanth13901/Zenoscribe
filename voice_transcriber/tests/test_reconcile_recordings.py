"""scripts/reconcile_recordings.py - backend-agnostic drift detection
(orphaned storage objects, DB rows pointing at missing objects).
"""
import importlib.util
import sys
from pathlib import Path

import pytest

from voice_transcriber import db, storage

SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "reconcile_recordings.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("reconcile_recordings", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def reconcile(isolated_recordings, isolated_db):
    return _load_script()


def _upload(user_id, rec_id, tmp_path, content=b"data"):
    src = tmp_path / f"{rec_id}.wav"
    src.write_bytes(content)
    key = storage.recording_key(user_id, rec_id, ".wav")
    storage.get_storage().upload(key, src, "audio/wav")
    return key


def test_reports_no_drift_when_storage_and_db_agree(reconcile, tmp_path, make_user, capsys):
    user_id = make_user("reco_user", "RecoPass123!")
    wav_key = _upload(user_id, "rec-1", tmp_path)
    txt_key = storage.recording_key(user_id, "rec-1", ".txt")
    storage.get_storage().upload_text(txt_key, "hello")
    db.add_recording("rec-1", user_id, wav_key, txt_key, "2026-01-01T00:00:00", 1.0, 1, "hello", "transcribe")

    sys.argv = ["reconcile_recordings.py"]
    reconcile.main()
    out = capsys.readouterr().out
    assert "Orphaned objects (no DB row): 0" in out
    assert "DB rows pointing at missing objects: 0" in out


def test_reports_orphaned_object_with_no_db_row(reconcile, tmp_path, make_user, capsys):
    user_id = make_user("orphan_user", "OrphanPass123!")
    orphan_key = _upload(user_id, "orphan-rec", tmp_path)

    sys.argv = ["reconcile_recordings.py"]
    reconcile.main()
    out = capsys.readouterr().out
    assert "Orphaned objects (no DB row): 1" in out
    assert orphan_key in out


def test_reports_db_row_pointing_at_missing_object(reconcile, make_user, capsys):
    user_id = make_user("missing_user", "MissingPass123!")
    wav_key = storage.recording_key(user_id, "missing-rec", ".wav")
    txt_key = storage.recording_key(user_id, "missing-rec", ".txt")
    # No actual upload - DB row references objects that don't exist.
    db.add_recording("missing-rec", user_id, wav_key, txt_key, "2026-01-01T00:00:00", 1.0, 1, "x", "transcribe")

    sys.argv = ["reconcile_recordings.py"]
    reconcile.main()
    out = capsys.readouterr().out
    assert "DB rows pointing at missing objects: 2" in out
    assert wav_key in out and txt_key in out


def test_delete_flag_removes_orphans_but_never_touches_db(reconcile, tmp_path, make_user, capsys):
    user_id = make_user("delete_user", "DeletePass123!")
    orphan_key = _upload(user_id, "to-delete", tmp_path)
    assert storage.get_storage().exists(orphan_key)

    sys.argv = ["reconcile_recordings.py", "--delete"]
    reconcile.main()

    assert not storage.get_storage().exists(orphan_key)
    assert db.list_recordings(limit=10) == []  # nothing to touch - always was empty


def test_live_scratch_files_are_never_reported_as_orphans(reconcile, isolated_recordings, capsys):
    from voice_transcriber import config

    scratch = config.live_scratch_dir() / "in-progress-session.wav"
    scratch.write_bytes(b"still recording")

    sys.argv = ["reconcile_recordings.py"]
    reconcile.main()
    out = capsys.readouterr().out
    assert "Orphaned objects (no DB row): 0" in out
