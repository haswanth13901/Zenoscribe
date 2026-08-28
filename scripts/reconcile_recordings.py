"""One-off reconciliation for stored recording objects vs. the `recordings`
table. Backend-agnostic (works against STORAGE_BACKEND=local or =minio) via
voice_transcriber.storage - see that package for the object-key scheme.

Written for the swallowed-exception bug in translate.py's old save path
(single try/except around transcript write + DB insert, since split into
three independent ones in _save_translate_session) - a failure partway
through could leave a recording object with no transcript and no DB row, or
a DB row pointing at an object that never got written. Not translate-specific
though: the same drift could happen anywhere storage and the DB disagree
(including transient MinIO failures - see the storage upload try/excepts in
transcribe.py/translate.py/routers/uploads.py, all deliberately
best-effort).

Dry-run by default - only reports. Pass --delete to remove orphaned objects
(objects in storage with no matching DB row). Never touches the DB or
deletes a DB row - a row with a missing object is reported only, since
guessing at which object it should have pointed to isn't safe to automate.

Usage:
    python scripts/reconcile_recordings.py            # report only
    python scripts/reconcile_recordings.py --delete   # also delete orphan objects
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_transcriber import config, db, storage  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delete", action="store_true",
        help="Delete orphaned objects (no matching DB row) instead of just reporting them",
    )
    args = parser.parse_args()

    store = storage.get_storage()
    print(f"STORAGE_BACKEND={config.STORAGE_BACKEND}")

    rows = db.list_recordings(limit=1_000_000)
    known_keys = set()
    for r in rows:
        known_keys.add(r["wav_file"])
        known_keys.add(r["txt_file"])

    stored_keys = set(store.list_keys())
    orphans = sorted(stored_keys - known_keys)

    missing = []
    for r in rows:
        for key in (r["wav_file"], r["txt_file"]):
            if not store.exists(key):
                missing.append((r["id"], key))

    print(f"Orphaned objects (no DB row): {len(orphans)}")
    for key in orphans:
        print(f"  {key}")
    print(f"DB rows pointing at missing objects: {len(missing)}")
    for rec_id, key in missing:
        print(f"  {rec_id} -> {key}")

    if args.delete:
        for key in orphans:
            store.delete(key)
        print(f"\nDeleted {len(orphans)} orphaned object(s).")
    elif orphans:
        print("\nDry run - re-run with --delete to remove the orphaned objects listed above.")


if __name__ == "__main__":
    main()
