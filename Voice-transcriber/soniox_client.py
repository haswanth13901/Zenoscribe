import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["SONIOX_API_KEY"]
REST = "https://api.soniox.com"
WS_URL = "wss://stt-rt.soniox.com/transcribe-websocket"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

ASYNC_MODEL = "stt-async-preview"
RT_MODEL = "stt-rt-preview"


class SpeakerLabeler:
    """Maps Soniox speaker IDs to stable user-1, user-2... in first-heard order."""

    def __init__(self):
        self.order = []

    def label(self, speaker_id):
        # Fall back to user-1 when diarization hasn't attached an ID yet.
        # Returning None here would cause tokens to be silently discarded.
        if speaker_id is None:
            return "user-1" if not self.order else f"user-{len(self.order)}"
        if speaker_id not in self.order:
            self.order.append(speaker_id)
        return f"user-{self.order.index(speaker_id) + 1}"

    def reset(self):
        self.order = []


def rt_config(sample_rate=16000, language_hints=None):
    """Realtime WebSocket handshake config."""
    cfg = {
        "api_key": API_KEY,
        "model": RT_MODEL,
        "audio_format": "pcm_s16le",
        "sample_rate": sample_rate,
        "num_channels": 1,
        "enable_speaker_diarization": True,
    }
    if language_hints:
        cfg["language_hints"] = language_hints
    return cfg


def transcribe_file(path, poll_interval=2.0, language_hints=("en",)):
    """Upload a file, wait for the job, return merged speaker turns."""
    with open(path, "rb") as f:
        resp = requests.post(f"{REST}/v1/files", headers=HEADERS, files={"file": f})
    resp.raise_for_status()
    file_id = resp.json()["id"]

    body = {
        "file_id": file_id,
        "model": ASYNC_MODEL,
        "enable_speaker_diarization": True,
    }
    if language_hints:
        body["language_hints"] = list(language_hints)

    resp = requests.post(f"{REST}/v1/transcriptions", headers=HEADERS, json=body)
    resp.raise_for_status()
    job_id = resp.json()["id"]

    while True:
        status = requests.get(
            f"{REST}/v1/transcriptions/{job_id}", headers=HEADERS
        ).json()
        state = status.get("status")
        if state == "completed":
            break
        if state == "error":
            raise RuntimeError(status.get("error_message", "transcription failed"))
        time.sleep(poll_interval)

    tokens = requests.get(
        f"{REST}/v1/transcriptions/{job_id}/transcript", headers=HEADERS
    ).json()["tokens"]

    return merge_tokens(tokens)


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