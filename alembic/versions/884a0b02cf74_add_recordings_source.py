"""add recordings.source

Adds a `source` column to `recordings` distinguishing how a recording was
produced: 'transcribe' (live Recorder), 'translate' (live Translate), or
'upload' (batch upload - reserved; nothing writes it yet, see db.py).

Backfill rule for existing rows: a row is 'translate' if its id contains the
"-translate-" session-name marker that translate.py stamps into every
session id it generates (`{stamp}-{username}-translate-{uuid}`, vs.
transcribe.py's `{stamp}-{username}-{uuid}`); every other existing row is
'transcribe', since the live Recorder is the only source that wrote
recordings before this migration (batch upload never has).

Revision ID: 884a0b02cf74
Revises: b9a728687f5b
Create Date: 2026-08-16 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = '884a0b02cf74'
down_revision: Union[str, Sequence[str], None] = 'b9a728687f5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE recordings ADD COLUMN source TEXT")

    op.execute("""
        UPDATE recordings
        SET source = CASE WHEN id LIKE '%-translate-%' THEN 'translate'
                           ELSE 'transcribe' END
    """)

    op.execute("""
        ALTER TABLE recordings
        ADD CONSTRAINT recordings_source_check
        CHECK (source IN ('transcribe', 'translate', 'upload'))
    """)

    op.execute("ALTER TABLE recordings ALTER COLUMN source SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE recordings DROP CONSTRAINT recordings_source_check")
    op.execute("ALTER TABLE recordings DROP COLUMN source")
