import os
import time
import requests
from dotenv import load_dotenv

REST = "https://api.soniox.com"
WS_URL = "wss://stt-rt.soniox.com/transcribe-websocket"

ASYNC_MODEL = "stt-async-v5"
RT_MODEL = "stt-rt-v5"
BATCH_POLL_TIMEOUT = 600

def get_api_key():
    load_dotenv(override=True)
    return os.environ["SONIOX_API_KEY"]

def get_headers():
    return {"Authorization": "Bearer " + get_api_key()}

def delete_remote_file(file_id):
    try:
        resp = requests.delete(f"{REST}/v1/files/{file_id}", headers=get_headers())
        resp.raise_for_status()
    except requests.RequestException:
        pass

def delete_transcription(job_id):
    try:
        resp = requests.delete(f"{REST}/v1/transcriptions/{job_id}", headers=get_headers())
        resp.raise_for_status()
    except requests.RequestException:
        try:
            resp = requests.post(
                f"{REST}/v1/transcriptions/{job_id}/cancel", headers=get_headers()
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


def rt_config(sample_rate=16000, language_hints=None):
    """Realtime WebSocket handshake config."""
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
    return cfg


# --------------------------------------------------------------- translation

TTS_WS_URL = "wss://tts-rt.soniox.com/tts-websocket"
TTS_MODEL = "tts-rt-v1"
TTS_SAMPLE_RATE = 24000  # Soniox TTS default for pcm_s16le


def translate_stt_config(mode, target_language=None, language_a=None,
                         language_b=None, sample_rate=16000):
    """STT config with a translation block.

    mode 'one_way': detected speech -> target_language.
    mode 'two_way': bidirectional between language_a and language_b.

    Endpoint detection is on so each utterance closes promptly, which is what
    lets the TTS side speak one sentence at a time.
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


def transcribe_file(path, poll_interval=2.0, timeout=BATCH_POLL_TIMEOUT, language_hints=("en",)):
    """Upload a file, wait for the job, return merged speaker turns."""
    with open(path, "rb") as f:
        resp = requests.post(f"{REST}/v1/files", headers=get_headers(), files={"file": f})
    resp.raise_for_status()
    file_id = resp.json()["id"]

    body = {
        "file_id": file_id,
        "model": ASYNC_MODEL,
        "enable_speaker_diarization": True,
    }
    if language_hints:
        body["language_hints"] = list(language_hints)

    job_id = None
    resp = requests.post(f"{REST}/v1/transcriptions", headers=get_headers(), json=body)
    resp.raise_for_status()
    job_id = resp.json()["id"]

    start = time.time()
    try:
        while True:
            status = requests.get(
                f"{REST}/v1/transcriptions/{job_id}", headers=get_headers()
            ).json()
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

        tokens = requests.get(
            f"{REST}/v1/transcriptions/{job_id}/transcript", headers=get_headers()
        ).json()["tokens"]

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