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
from websockets.exceptions import ConnectionClosedOK

try:
    from . import auth
    from . import config
    from . import db
    from . import rate_limit
    from . import soniox_client as sx
except ImportError:  # run flat from inside the package dir
    import auth
    import config
    import db
    import rate_limit
    import soniox_client as sx

log = logging.getLogger("transcribe")

router = APIRouter()


@router.websocket("/ws")
async def live(client: WebSocket):
    await client.accept()
    # Browsers can't set Authorization headers on a WebSocket. The client sends
    # a one-time auth frame after the socket opens so the JWT never appears in
    # the request URL/query string.
    ws_user, hello = await auth.user_from_ws(client)
    if not ws_user:
        await client.close(code=4401)
        return
    user_id = ws_user["id"]
    username = ws_user["username"]
    # Each connection spawns a real Soniox session (real cost, held server
    # resources) - throttle new connections per user before doing anything
    # else, same as the upload endpoints' per_user() limit but checked here
    # directly since WS auth happens via a frame, not a header FastAPI's
    # Depends() can see.
    if not rate_limit.hit(f"ws-connect:{user_id}", 20, 300):
        await client.send_json({"type": "error", "message": "Too many connection attempts, try again shortly"})
        await client.close(code=4429)
        return
    num_speakers = hello.get("num_speakers")
    await client.send_json({"type": "ready"})
    labeler = sx.SpeakerLabeler()
    loop = asyncio.get_event_loop()

    alive = True
    finished = asyncio.Event()
    write_queue = asyncio.Queue()

    async def async_touch_seen(uid):
        await asyncio.to_thread(db.touch_seen, uid)

    async def async_add_recording(rec_id, user_id, wav_file, txt_file,
                                  started_at, duration, turn_count, preview):
        await asyncio.to_thread(
            db.add_recording,
            rec_id,
            user_id,
            wav_file,
            txt_file,
            started_at,
            duration,
            turn_count,
            preview,
            "transcribe",
        )

    async def async_write_text(path, content):
        await asyncio.to_thread(path.write_text, content, encoding="utf-8")

    async def async_get_wav_duration(path):
        def read_duration():
            frames = wave.open(str(path), "rb")
            try:
                return frames.getnframes() / float(frames.getframerate() or 1)
            finally:
                frames.close()

        return await asyncio.to_thread(read_duration)

    async def async_delete_file(path):
        await asyncio.to_thread(path.unlink)

    async def audio_writer():
        while True:
            chunk = await write_queue.get()
            if chunk is None:
                write_queue.task_done()
                break
            try:
                await asyncio.to_thread(wf.writeframes, chunk)
            finally:
                write_queue.task_done()

    await async_touch_seen(user_id)
    state = {
        "speaker": None,
        "buf_tokens": [],
        "start": None,
        "last_final": loop.time(),
        "votes": {},  # speaker label -> finalized tokens seen this turn
        "streak_label": None,  # speaker of the current consecutive run
        "streak": 0,  # length of that run
        "pending_tokens": [],  # minority-speaker tokens that may start the next turn
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
    writer_task = asyncio.create_task(audio_writer())

    turns = []

    def _buf_text():
        return "".join(state["buf_tokens"])

    async def _flush_locked():
        text = _buf_text().strip()
        if not text:
            state["buf_tokens"], state["start"] = [], None
            state["votes"] = {}
            state["pending_tokens"] = []
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
        state["buf_tokens"], state["start"] = [], None
        state["votes"] = {}
        state["pending_tokens"] = []
        await safe_send({"type": "final", **turn})

    async def flush():
        """Emit the buffered turn as final and reset. Safe to call any time.

        The turn is attributed to whichever speaker most of its tokens were
        assigned to, so a wrong label on the opening word gets corrected by
        the rest of the sentence.
        """
        async with lock:
            await _flush_locked()

    try:
        async with connect(sx.WS_URL, max_size=None) as upstream:
            await upstream.send(json.dumps(
                sx.rt_config(language_hints=config.LANGUAGE_HINTS, num_speakers=num_speakers)
            ))
            log.info("session %s started", session)

            async def pump_audio():
                nonlocal alive
                try:
                    while True:
                        chunk = await client.receive_bytes()
                        await write_queue.put(chunk)
                        await upstream.send(chunk)
                except (WebSocketDisconnect, RuntimeError):
                    alive = False
                    try:
                        await upstream.send(b"")  # signals end of stream
                    except Exception:
                        pass
                except Exception:
                    alive = False
                    log.exception("client audio task error")
                    try:
                        await upstream.send(b"")
                    except Exception:
                        pass

            async def pump_results():
                try:
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
                                    carried_tokens = state["pending_tokens"]
                                    state["buf_tokens"] = (
                                        state["buf_tokens"][: -len(carried_tokens)]
                                        if carried_tokens else state["buf_tokens"]
                                    )
                                    await _flush_locked()
                                    state["speaker"] = label
                                    state["votes"] = {label: streak}
                                    state["streak_label"] = label
                                    state["streak"] = streak
                                    state["start"] = tok.get("start_ms", 0) / 1000
                                    state["buf_tokens"] = carried_tokens + [tok["text"]]
                                    state["pending_tokens"] = []
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
                                state["buf_tokens"].append(tok["text"])
                                # Hold recent minority tokens in case they turn out
                                # to be the start of the next speaker's turn.
                                if label == state["streak_label"] and streak > 1:
                                    state["pending_tokens"].append(tok["text"])
                                else:
                                    state["pending_tokens"] = [tok["text"]]
                                state["last_final"] = loop.time()

                        async with lock:
                            confirmed = _buf_text()
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
                except ConnectionClosedOK:
                    log.info("upstream closed cleanly")
                except Exception as exc:
                    log.exception("upstream bridge error")
                    if alive:
                        await safe_send({"type": "error", "message": str(exc)})
                finally:
                    await flush()
                    finished.set()
                    try:
                        await client.close()
                    except Exception:
                        pass

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
                        text = _buf_text()
                        pending = bool(text.strip())
                        # Trailing whitespace or punctuation means the word closed.
                        at_boundary = text != text.rstrip() or text.rstrip().endswith(
                            (".", "?", "!", ",", ";", ":")
                        )
                    if pending and at_boundary and idle > config.IDLE_FLUSH_SEC:
                        await flush()

            tasks = [
                asyncio.create_task(pump_audio()),
                asyncio.create_task(pump_results()),
                asyncio.create_task(watchdog()),
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception) and not isinstance(result, ConnectionClosedOK):
                    log.exception("session task failed", exc_info=result)

    except WebSocketDisconnect:
        log.info("client disconnected")
    except ConnectionClosedOK:
        log.info("soniox closed cleanly")
    except Exception as e:
        log.exception("bridge error")
        try:
            await safe_send({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        finished.set()
        await write_queue.put(None)
        try:
            await writer_task
        except Exception:
            log.exception("audio writer failed")
        try:
            await asyncio.to_thread(wf.close)
        except Exception:
            log.exception("failed to close wav file")

        if not turns:
            log.info("discarding empty session %s for %s", session, username)
            try:
                await async_delete_file(wav_path)
            except Exception:
                log.exception("failed to delete empty wav %s", wav_path)
            return

        txt_path = config.RECORDINGS / f"{session}.txt"
        await async_write_text(
            txt_path,
            "\n".join(
                f"[{(t['start'] or 0):.1f}s] {t['speaker']}: {t['text']}"
                for t in turns
            ),
        )

        try:
            duration = await async_get_wav_duration(wav_path)
        except Exception:
            duration = 0.0

        preview = " ".join(t["text"] for t in turns)[:160]
        try:
            await async_add_recording(
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
