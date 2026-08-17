"""One-off reconciliation for recordings/ vs. the `recordings` table.

Written for the swallowed-exception bug in translate.py's old save path
(single try/except around transcript write + DB insert, since split into
three independent ones in _save_translate_session) - a failure partway
through could leave a WAV on disk with no transcript and no DB row, or a DB
row pointing at a file that never got written. Not translate-specific
though: the same drift could happen anywhere recordings/ and the DB
disagree.

Dry-run by default - only reports. Pass --delete to remove orphaned files
(files on disk with no matching DB row). Never touches the DB or deletes a
DB row - a row with a missing file is reported only, since guessing at
which file it should have pointed to isn't safe to automate.

Usage:
    python scripts/reconcile_recordings.py            # report only
    python scripts/reconcile_recordings.py --delete   # also delete orphan files
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_transcriber import config, db  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delete", action="store_true",
        help="Delete orphaned files (no matching DB row) instead of just reporting them",
    )
    args = parser.parse_args()

    rows = db.list_recordings(limit=1_000_000)
    known_ids = {r["id"] for r in rows}

    orphan_wavs = [p for p in sorted(config.RECORDINGS.glob("*.wav")) if p.stem not in known_ids]
    orphan_txts = [p for p in sorted(config.RECORDINGS.glob("*.txt")) if p.stem not in known_ids]

    missing_files = []
    for r in rows:
        for filename in (r["wav_file"], r["txt_file"]):
            path = config.RECORDINGS / filename
            if not path.exists():
                missing_files.append((r["id"], path))

    print(f"Orphaned WAV files (no DB row): {len(orphan_wavs)}")
    for p in orphan_wavs:
        print(f"  {p}")
    print(f"Orphaned TXT files (no DB row): {len(orphan_txts)}")
    for p in orphan_txts:
        print(f"  {p}")
    print(f"DB rows pointing at missing files: {len(missing_files)}")
    for rec_id, p in missing_files:
        print(f"  {rec_id} -> {p}")

    if args.delete:
        for p in orphan_wavs + orphan_txts:
            p.unlink()
        print(f"\nDeleted {len(orphan_wavs) + len(orphan_txts)} orphaned file(s).")
    elif orphan_wavs or orphan_txts:
        print("\nDry run - re-run with --delete to remove the orphaned files listed above.")


if __name__ == "__main__":
    main()
