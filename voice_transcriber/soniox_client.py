import os
import time
import requests
from dotenv import load_dotenv

try:
    from . import config
except ImportError:  # run flat from inside the package dir
    import config

REST = os.environ.get("SONIOX_REST_URL", "https://api.soniox.com")
WS_URL = "wss://stt-rt.soniox.com/transcribe-websocket"

ASYNC_MODEL = "stt-async-v5"
RT_MODEL = "stt-rt-v5"
BATCH_POLL_TIMEOUT = 600

# Bounds for the optional speaker-count hint. Soniox diarizes without it, but
# telling it how many speakers to expect improves separation when it's known
# up front (e.g. a fixed meeting size). Out-of-range or unparseable values
# are dropped rather than sent upstream.
MIN_SPEAKERS = 1
MAX_SPEAKERS = 10


def clamp_num_speakers(num_speakers):
    if num_speakers is None:
        return None
    try:
        n = int(num_speakers)
    except (TypeError, ValueError):
        return None
    if n < MIN_SPEAKERS or n > MAX_SPEAKERS:
        return None
    return n


# Overridable from environment for testing/CI (e.g. a small value to fail fast).
UPLOAD_TIMEOUT = int(os.environ.get('SONIOX_UPLOAD_TIMEOUT', '30'))
POLL_REQUEST_TIMEOUT = int(os.environ.get('SONIOX_POLL_REQUEST_TIMEOUT', '10'))
TRANSCRIPTION_INIT_TIMEOUT = int(os.environ.get('SONIOX_TRANSCRIPTION_INIT_TIMEOUT', '10'))


def get_api_key():
    # Reload from the same dotenv file config.py resolved at import time (not
    # a bare `.env`) - otherwise a stray dev `.env` sitting next to
    # `.env.production` would silently override the production key on every
    # call, since override=True is needed for dev hot-reload of a rotated key.
    load_dotenv(config.ENV_FILE, override=True)
    return os.environ["SONIOX_API_KEY"]


def get_headers():
    return {"Authorization": "Bearer " + get_api_key()}


def delete_remote_file(file_id):
    try:
        resp = requests.delete(f"{REST}/v1/files/{file_id}", headers=get_headers(), timeout=POLL_REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        pass


def delete_transcription(job_id):
    try:
        resp = requests.delete(
            f"{REST}/v1/transcriptions/{job_id}", headers=get_headers(), timeout=POLL_REQUEST_TIMEOUT
        )
        resp.raise_for_status()
    except requests.RequestException:
        try:
            resp = requests.post(
                f"{REST}/v1/transcriptions/{job_id}/cancel", headers=get_headers(), timeout=POLL_REQUEST_TIMEOUT
            )
            resp.raise_for_status()
        except requests.RequestException:
            pass


def cleanup_remote_resources(file_id=None, job_id=None):
    if job_id is not None:
        delete_transcription(job_id)
    if file_id is not None:
        delete_remote_file(file_id)


class SpeakerLabeler:
    """Maps Soniox speaker IDs to stable user-1, user-2... in first-heard order."""

    def __init__(self):
        self.order = []
        self.last_label = None

    def label(self, speaker_id):
        # Fall back to the current speaker when diarization hasn't attached an
        # ID yet. Returning None would cause tokens to be silently discarded.
        if speaker_id is None:
            return self.last_label or "user-1"
        if speaker_id not in self.order:
            self.order.append(speaker_id)
        label = f"user-{self.order.index(speaker_id) + 1}"
        self.last_label = label
        return label

    def reset(self):
        self.order = []
        self.last_label = None


def rt_config(sample_rate=16000, language_hints=None, num_speakers=None):
    cfg = {
        "api_key": get_api_key(),
        "model": RT_MODEL,
        "audio_format": "pcm_s16le",
        "sample_rate": sample_rate,
        "num_channels": 1,
        "enable_speaker_diarization": True,
    }
    if language_hints:
        cfg["language_hints"] = language_hints
    num_speakers = clamp_num_speakers(num_speakers)
    if num_speakers:
        cfg["num_speakers"] = num_speakers
    return cfg


TTS_WS_URL = "wss://tts-rt.soniox.com/tts-websocket"
# v1, not v2: server.py's voice list ("Maya", "Adrian") is v1's roster -
# "Maya" doesn't exist on tts-rt-v2 (confirmed against GET /v1/tts-models).
TTS_MODEL = "tts-rt-v1"
TTS_SAMPLE_RATE = 24000  # Soniox TTS default for pcm_s16le


def translate_stt_config(mode, target_language=None, language_a=None,
                         language_b=None, sample_rate=16000, diarize=False,
                         num_speakers=None):
    """STT config with a translation block.

    mode 'one_way': detected speech -> target_language.
    mode 'two_way': bidirectional between language_a and language_b.

    Endpoint detection is on so each utterance closes promptly, which is what
    lets the TTS side speak one sentence at a time. diarize adds per-token
    speaker ids, used to label who said what in the captions. num_speakers
    is only meaningful alongside diarize.
    """
    cfg = {
        "api_key": get_api_key(),
        "model": RT_MODEL,
        "audio_format": "pcm_s16le",
        "sample_rate": sample_rate,
        "num_channels": 1,
        "enable_language_identification": True,
        "enable_endpoint_detection": True,
    }
    if diarize:
        cfg["enable_speaker_diarization"] = True
        num_speakers = clamp_num_speakers(num_speakers)
        if num_speakers:
            cfg["num_speakers"] = num_speakers
    if mode == "one_way":
        cfg["translation"] = {
            "type": "one_way",
            "target_language": target_language,
        }
    elif mode == "two_way":
        cfg["translation"] = {
            "type": "two_way",
            "language_a": language_a,
            "language_b": language_b,
        }
    else:
        raise ValueError(f"unknown translation mode: {mode}")
    return cfg


def tts_config(voice, language, stream_id, sample_rate=TTS_SAMPLE_RATE):
    """One TTS stream config message. One stream per utterance."""
    return {
        "api_key": get_api_key(),
        "model": TTS_MODEL,
        "language": language,
        "voice": voice,
        "audio_format": "pcm_s16le",
        "sample_rate": sample_rate,
        "stream_id": stream_id,
    }


# Test-only fake mode (None unless set by tests). Use set_test_fake_mode()/get_test_fake_mode().
_TEST_FAKE_MODE = None


def set_test_fake_mode(mode: str):
    """Set test fake mode. Accepted values: 'timeout','runtime','ok', or None to clear."""
    global _TEST_FAKE_MODE
    _TEST_FAKE_MODE = mode


def get_test_fake_mode():
    return _TEST_FAKE_MODE


def transcribe_file(
    path, poll_interval=2.0, timeout=BATCH_POLL_TIMEOUT, language_hints=("en",),
    target_language=None, num_speakers=None,
):
    """Upload a file, wait for the job, return merged speaker turns.

    If target_language is provided, request a one-way translation from Soniox
    and return the merged translated turns (tokens where translation_status == 'translation').

    TEST HOOK: when a test fake mode is set (via set_test_fake_mode) or the
    TEST_FAKE_TRANSCRIBE_MODE environment variable is present, this function
    simulates behavior for end-to-end tests without contacting Soniox.
    Allowed values: 'timeout', 'runtime', 'ok'.
    """
    fake_mode = get_test_fake_mode() or os.environ.get('TEST_FAKE_TRANSCRIBE_MODE')
    if fake_mode:
        if fake_mode == 'timeout':
            raise TimeoutError('simulated upstream timeout (TEST_FAKE_TRANSCRIBE_MODE)')
        if fake_mode == 'runtime':
            raise RuntimeError('simulated upstream runtime error (TEST_FAKE_TRANSCRIBE_MODE)')
        if fake_mode == 'ok':
            if target_language:
                return [{
                    "speaker": "spk1",
                    "text": "Hello world",
                    "translation": "Bonjour le monde",
                    "start": 0.0,
                    "end": 1.0,
                }]
            return [{"speaker": "spk1", "text": "Hello world", "start": 0.0, "end": 1.0}]

    job_id = None
    try:
        with open(path, "rb") as f:
            resp = requests.post(f"{REST}/v1/files", headers=get_headers(), files={"file": f}, timeout=UPLOAD_TIMEOUT)
        resp.raise_for_status()
        file_id = resp.json()["id"]
    except requests.Timeout:
        raise TimeoutError(f"upload to Soniox timed out after {UPLOAD_TIMEOUT}s")
    except requests.RequestException as e:
        raise RuntimeError(f"failed to upload file to Soniox: {e}")

    body = {
        "file_id": file_id,
        "model": ASYNC_MODEL,
        "enable_speaker_diarization": True,
    }
    num_speakers = clamp_num_speakers(num_speakers)
    if num_speakers:
        body["num_speakers"] = num_speakers
    if language_hints:
        body["language_hints"] = list(language_hints)
    if target_language:
        body["translation"] = {"type": "one_way", "target_language": target_language}

    try:
        resp = requests.post(
            f"{REST}/v1/transcriptions", headers=get_headers(), json=body, timeout=TRANSCRIPTION_INIT_TIMEOUT
        )
        resp.raise_for_status()
        job_id = resp.json()["id"]
    except requests.Timeout:
        cleanup_remote_resources(file_id=file_id, job_id=None)
        raise TimeoutError(f"starting transcription timed out after {TRANSCRIPTION_INIT_TIMEOUT}s")
    except requests.RequestException as e:
        cleanup_remote_resources(file_id=file_id, job_id=None)
        raise RuntimeError(f"failed to start transcription: {e}")

    start = time.time()
    try:
        while True:
            try:
                status_resp = requests.get(
                    f"{REST}/v1/transcriptions/{job_id}", headers=get_headers(), timeout=POLL_REQUEST_TIMEOUT
                )
                status = status_resp.json()
            except requests.Timeout:
                # Treat poll timeouts as transient; fail fast only if overall timeout exceeded
                if time.time() - start >= timeout:
                    raise TimeoutError(f"remote transcription did not complete within {timeout}s")
                time.sleep(poll_interval)
                continue
            except requests.RequestException as e:
                raise RuntimeError(f"error polling transcription status: {e}")

            state = status.get("status")
            if state == "completed":
                break
            if state == "error":
                raise RuntimeError(status.get("error_message", "transcription failed"))
            if time.time() - start >= timeout:
                raise TimeoutError(
                    f"remote transcription did not complete within {timeout}s"
                )
            time.sleep(poll_interval)

        try:
            tokens = requests.get(
                f"{REST}/v1/transcriptions/{job_id}/transcript", headers=get_headers(), timeout=POLL_REQUEST_TIMEOUT
            ).json()["tokens"]
        except requests.Timeout:
            raise TimeoutError(f"fetching transcript timed out after {POLL_REQUEST_TIMEOUT}s")
        except requests.RequestException as e:
            raise RuntimeError(f"failed to fetch transcript: {e}")

        if target_language:
            original_tokens = [t for t in tokens if t.get("translation_status") != "translation"]
            trans_tokens = [t for t in tokens if t.get("translation_status") == "translation"]
            return merge_translated_turns(original_tokens, trans_tokens)

        return merge_tokens(tokens)
    finally:
        cleanup_remote_resources(file_id=file_id, job_id=job_id)


def merge_tokens(tokens):
    """Collapse token stream into consecutive same-speaker turns."""
    labeler = SpeakerLabeler()
    turns = []
    for t in tokens:
        label = labeler.label(t.get("speaker"))
        start = t.get("start_ms", 0) / 1000
        end = t.get("end_ms", 0) / 1000
        if turns and turns[-1]["speaker"] == label:
            turns[-1]["text"] += t["text"]
            turns[-1]["end"] = end
        else:
            turns.append(
                {
                    "speaker": label,
                    "text": t["text"].lstrip(),
                    "start": start,
                    "end": end,
                }
            )
    for turn in turns:
        turn["text"] = turn["text"].strip()
    return turns


def merge_translated_turns(original_tokens, trans_tokens):
    """Pair original-language turns with their translations for
    /transcribe/translate, so the caller gets both instead of just the
    translation.

    Original and translation tokens are merged into turns separately (via
    merge_tokens) rather than interleaved in one pass, since the two streams'
    relative ordering in the token list isn't guaranteed. Both streams
    segment the same underlying audio/diarization, so they line up
    index-for-index in the normal case; a count mismatch just means a
    trailing turn is missing its text or its translation rather than
    crashing.
    """
    original_turns = merge_tokens(original_tokens)
    trans_turns = merge_tokens(trans_tokens)
    turns = []
    for i in range(max(len(original_turns), len(trans_turns))):
        orig = original_turns[i] if i < len(original_turns) else None
        trans = trans_turns[i] if i < len(trans_turns) else None
        base = orig or trans
        turns.append({
            "speaker": base["speaker"],
            "text": orig["text"] if orig else "",
            "translation": trans["text"] if trans else "",
            "start": base["start"],
            "end": base["end"],
        })
    return turns
