"""Shared settings.

Kept separate so the auth layer and the transcription engine can both read
paths without importing each other.
"""

from pathlib import Path

RECORDINGS = Path("recordings")
RECORDINGS.mkdir(exist_ok=True)

STATIC_DIR = "static"

# --------------------------------------------------- transcription tuning
# These only affect the engine in transcribe.py. Adjust them there-and-only
# there when tuning turn detection; nothing in the auth layer reads them.

# Flush a turn this many seconds after the last finalized token arrives.
# Must exceed a normal speaking pause, or turns split mid-sentence.
IDLE_FLUSH_SEC = 1.6

# Safety valve only - long enough that it rarely fires mid-thought.
MAX_TURN_CHARS = 400

# Punctuation alone doesn't end a turn; the speaker must also have paused.
SENTENCE_PAUSE_SEC = 0.5

# A turn is labeled by majority vote across its tokens, not by whichever
# speaker won the first word - that token is the one diarization is least
# sure about. A challenger must produce this many consecutive tokens to take
# over the turn. Raise to 3-4 if speakers still bleed into each other; lower
# to 1 to switch on the first disagreeing token.
VOTE_MARGIN = 2

# Language passed to Soniox. ["en"] locks English; add more for code-switching.
LANGUAGE_HINTS = ["en"]

# ------------------------------------------------------------- debugging
# Log every raw frame Soniox returns.
DEBUG_SONIOX = False
# Log the raw speaker ID on each finalized token, to check whether Soniox is
# separating speakers at all.
DEBUG_SPEAKERS = False