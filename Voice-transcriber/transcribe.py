"""Realtime transcription engine.

Owns the Soniox WebSocket bridge and all turn-detection logic: majority-vote
speaker labeling, streak-based takeover, and the idle flush watchdog.

Tuning constants live in config.py. The auth layer never touches this file,
so the engine can be changed independently of login and admin behaviour.
"""

import asyncio
import json
import logging
import uuid
import wave
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from websockets import connect 

import auth
import config
import db
import soniox_client as sx

log = logging.getLogger("transcribe")

router = APIRouter()


@router.websocket("/ws")
async def live(client: WebSocket):
    # Browsers can't set Authorization headers on a WebSocket, so the token
    # arrives as ?token=... and is validated before the socket is accepted.
    ws_user = auth.user_from_ws(client)
    if not ws_user:
        await client.close(code=4401)
        return
    user_id = ws_user["id"]
    username = ws_user["username"]
    db.touch_seen(user_id)

    await client.accept()
    labeler = sx.SpeakerLabeler()
    loop = asyncio.get_event_loop()

    alive = True
    finished = asyncio.Event()

    # Turn state shared between the result pump and the watchdog.
    state = {
        "speaker": None,
        "buf": "",
        "start": None,
        "last_final": loop.time(),
        "votes": {},  # speaker label -> finalized tokens seen this turn
        "streak_label": None,  # speaker of the current consecutive run
        "streak": 0,  # length of that run
        "pending": "",  # minority-speaker text that may start the next turn
    }
    lock = asyncio.Lock()

    async def safe_send(payload):
        """Send to browser, silently skipping once it has disconnected."""
        nonlocal alive
        if not alive:
            return
        try:
            await client.send_json(payload)
        except (WebSocketDisconnect, RuntimeError):
            alive = False

    started_at = datetime.now()
    stamp = started_at.strftime("%Y%m%d-%H%M%S")
    session = f"{stamp}-{username}-{uuid.uuid4().hex[:6]}"
    wav_path = config.RECORDINGS / f"{session}.wav"

    wf = wave.open(str(wav_path), "wb")
    wf.setnchannels(1)
    wf.setsampwidth(2)  # int16
    wf.setframerate(16000)

    turns = []

    async def flush():
        """Emit the buffered turn as final and reset. Safe to call any time.

        The turn is attributed to whichever speaker most of its tokens were
        assigned to, so a wrong label on the opening word gets corrected by
        the rest of the sentence.
        """
        async with lock:
            text = state["buf"].strip()
            if not text:
                state["buf"], state["start"] = "", None
                state["votes"] = {}
                state["pending"] = ""
                return
            if state["votes"]:
                winner = max(state["votes"], key=state["votes"].get)
            else:
                winner = state["speaker"] or "user-1"
            turn = {
                "speaker": winner,
                "text": text,
                "start": state["start"],
            }
            turns.append(turn)
            state["buf"], state["start"] = "", None
            state["votes"] = {}
            state["pending"] = ""
        await safe_send({"type": "final", **turn})

    try:
        async with connect(sx.WS_URL, max_size=None) as upstream:
            await upstream.send(json.dumps(sx.rt_config(language_hints=config.LANGUAGE_HINTS)))
            log.info("session %s started", session)

            async def pump_audio():
                nonlocal alive
                try:
                    while True:
                        chunk = await client.receive_bytes()
                        wf.writeframes(chunk)
                        await upstream.send(chunk)
                except (WebSocketDisconnect, RuntimeError):
                    alive = False
                    try:
                        await upstream.send(b"")  # signals end of stream
                    except Exception:
                        pass

            async def pump_results():
                async for raw in upstream:
                    if config.DEBUG_SONIOX:
                        log.info("SONIOX: %s", str(raw)[:400])

                    payload = json.loads(raw)

                    if payload.get("error_code"):
                        await safe_send(
                            {
                                "type": "error",
                                "message": payload.get("error_message"),
                            }
                        )
                        continue

                    tokens = payload.get("tokens", [])
                    if not tokens:
                        continue

                    # Soniox resends the whole non-final hypothesis on each frame,
                    # so partials are rebuilt per frame and never accumulated.
                    partial_text = ""
                    partial_speaker = None

                    for tok in tokens:
                        label = labeler.label(tok.get("speaker"))

                        if not tok.get("is_final"):
                            partial_text += tok["text"]
                            partial_speaker = label
                            continue

                        if config.DEBUG_SPEAKERS:
                            log.info(
                                "tok spk=%s -> %s  %r",
                                tok.get("speaker"), label, tok["text"],
                            )

                        async with lock:
                            holder = state["speaker"]
                            # Consecutive tokens from a speaker other than the
                            # current holder. A single disagreeing token is
                            # noise; a sustained run is a real turn change.
                            if label == state["streak_label"]:
                                streak = state["streak"] + 1
                            else:
                                streak = 1
                            state["streak_label"] = label
                            state["streak"] = streak
                            takeover = (
                                holder is not None
                                and label != holder
                                and streak >= config.VOTE_MARGIN
                            )

                        if takeover:
                            # The tokens that formed this streak belong to the
                            # new speaker, so move them out of the old turn.
                            async with lock:
                                carried = state["pending"]
                                state["buf"] = state["buf"][: len(state["buf"]) - len(carried)]
                            await flush()
                            async with lock:
                                state["speaker"] = label
                                state["votes"] = {label: streak}
                                state["streak_label"] = label
                                state["streak"] = streak
                                state["start"] = tok.get("start_ms", 0) / 1000
                                state["buf"] = carried + tok["text"]
                                state["pending"] = ""
                                state["last_final"] = loop.time()
                            continue

                        async with lock:
                            state["votes"][label] = state["votes"].get(label, 0) + 1
                            # Attribute the in-progress turn to the current leader.
                            state["speaker"] = max(
                                state["votes"], key=state["votes"].get
                            )
                            if state["start"] is None:
                                state["start"] = tok.get("start_ms", 0) / 1000
                            state["buf"] += tok["text"]
                            # Hold recent minority tokens in case they turn out
                            # to be the start of the next speaker's turn.
                            if label == state["streak_label"] and streak > 1:
                                state["pending"] += tok["text"]
                            else:
                                state["pending"] = tok["text"]
                            state["last_final"] = loop.time()

                    async with lock:
                        confirmed = state["buf"]
                        speaker = state["speaker"]

                    # Confirmed text plus the live tail, as one continuous line.
                    live_text = (confirmed + " " + partial_text).strip()
                    if live_text:
                        await safe_send(
                            {
                                "type": "partial",
                                "speaker": partial_speaker or speaker or "user-1",
                                "text": live_text,
                            }
                        )

                    stripped = confirmed.strip()
                    async with lock:
                        idle = loop.time() - state["last_final"]
                    # "Sure. Definitely." should stay one turn - only close on
                    # punctuation if the speaker has actually stopped.
                    if stripped and (
                        (stripped.endswith((".", "?", "!"))
                         and idle > config.SENTENCE_PAUSE_SEC)
                        or len(stripped) > config.MAX_TURN_CHARS
                    ):
                        await flush()

                await flush()
                finished.set()

            async def watchdog():
                """Flush a quiet turn without waiting for punctuation.

                Soniox finalizes in bursts, so a gap between bursts can look
                like silence mid-sentence. Requiring a completed word stops
                turns splitting inside a word ("Def" / "initely").
                """
                while not finished.is_set():
                    await asyncio.sleep(0.25)
                    async with lock:
                        idle = loop.time() - state["last_final"]
                        text = state["buf"]
                        pending = bool(text.strip())
                        # Trailing whitespace or punctuation means the word closed.
                        at_boundary = text != text.rstrip() or text.rstrip().endswith(
                            (".", "?", "!", ",", ";", ":")
                        )
                    if pending and at_boundary and idle > config.IDLE_FLUSH_SEC:
                        await flush()

            await asyncio.gather(pump_audio(), pump_results(), watchdog())

    except WebSocketDisconnect:
        log.info("client disconnected")
    except Exception as e:
        log.exception("bridge error")
        try:
            await safe_send({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        finished.set()
        wf.close()
        txt_path = config.RECORDINGS / f"{session}.txt"
        txt_path.write_text(
            "\n".join(
                f"[{(t['start'] or 0):.1f}s] {t['speaker']}: {t['text']}"
                for t in turns
            ),
            encoding="utf-8",
        )

        try:
            frames = wave.open(str(wav_path), "rb")
            duration = frames.getnframes() / float(frames.getframerate() or 1)
            frames.close()
        except Exception:
            duration = 0.0

        preview = " ".join(t["text"] for t in turns)[:160]
        try:
            db.add_recording(
                rec_id=session,
                user_id=user_id,
                wav_file=wav_path.name,
                txt_file=txt_path.name,
                started_at=started_at.isoformat(),
                duration=duration,
                turn_count=len(turns),
                preview=preview,
            )
        except Exception:
            log.exception("could not register recording %s", session)

        log.info(
            "saved %s for %s (%d turns, %.1fs)",
            session, username, len(turns), duration,
        )