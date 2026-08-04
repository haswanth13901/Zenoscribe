"""Real-time speech-to-speech translation engine.

A separate module from the transcription engine. It owns a three-way bridge:

    browser mic  ->  Soniox STT+translation  ->  (translated text)
    (translated text)  ->  Soniox TTS  ->  audio  ->  browser playback

The browser also receives the transcript/translation text so it can show
captions alongside the spoken output. Two language modes:

    one_way : auto-detect source, speak everything in one target language
    two_way : bidirectional between two chosen languages

Nothing here touches the transcription engine, auth rules aside. It depends
only on auth, soniox_client, and languages.
"""

import asyncio
import base64
import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from websockets import connect
from websockets.exceptions import ConnectionClosedOK

import auth
import languages
import soniox_client as sx

log = logging.getLogger("translate")

# Flip to True to log every token Soniox returns (status/lang/final/text).
# Use it to confirm whether translation tokens are actually arriving.
DEBUG_TOKENS = True

router = APIRouter()

# Cap the concurrent target-language TTS streams we open per session, so a
# runaway source can't spawn unbounded upstream connections.
MAX_ACTIVE_TTS = 4


@router.websocket("/ws/translate")
async def translate(client: WebSocket):
    await client.accept()

    # First frame authenticates (matches the transcription engine's pattern:
    # the JWT never rides in the URL). It also carries the session settings.
    try:
        hello = await client.receive_json()
    except Exception:
        await client.close(code=4400)
        return

    ws_user = auth.user_from_token(hello.get("token", "")) if isinstance(hello, dict) else None
    if not ws_user:
        await client.close(code=4401)
        return

    # ---- read + validate settings from the hello frame ----
    mode = hello.get("mode", "one_way")
    speak = bool(hello.get("speak", True))         # voice-out on/off
    voice = hello.get("voice", "Maya")

    if mode == "one_way":
        target = hello.get("target_language", "es")
        if not languages.is_valid(target):
            await _fail(client, "Unsupported target language")
            return
        stt_cfg = sx.translate_stt_config("one_way", target_language=target)
        # In one-way, everything is spoken in the single target language.
        tts_lang_for = lambda tok_lang: target
    elif mode == "two_way":
        lang_a = hello.get("language_a", "en")
        lang_b = hello.get("language_b", "es")
        if not (languages.is_valid(lang_a) and languages.is_valid(lang_b)):
            await _fail(client, "Unsupported language pair")
            return
        stt_cfg = sx.translate_stt_config(
            "two_way", language_a=lang_a, language_b=lang_b
        )
        # In two-way, a translated token's own language field tells us which
        # voice language to speak it in.
        tts_lang_for = lambda tok_lang: tok_lang or lang_b
    else:
        await _fail(client, "Unknown mode")
        return

    alive = True

    async def to_browser(payload):
        nonlocal alive
        if not alive:
            return
        try:
            await client.send_json(payload)
        except (WebSocketDisconnect, RuntimeError):
            alive = False

    try:
        async with connect(sx.WS_URL, max_size=None) as stt:
            await stt.send(json.dumps(stt_cfg))
            await to_browser({"type": "ready"})
            log.info("translate session for %s: mode=%s speak=%s",
                     ws_user["username"], mode, speak)

            # ---- browser mic -> STT ----
            async def pump_mic():
                nonlocal alive
                try:
                    while True:
                        msg = await client.receive()
                        if "bytes" in msg and msg["bytes"] is not None:
                            await stt.send(msg["bytes"])
                        elif "text" in msg and msg["text"]:
                            # A control frame, e.g. {"eof": true} on Stop.
                            ctrl = json.loads(msg["text"])
                            if ctrl.get("eof"):
                                await stt.send(b"")
                                break
                except (WebSocketDisconnect, RuntimeError, KeyError):
                    alive = False
                    try:
                        await stt.send(b"")
                    except Exception:
                        pass

            # ---- STT results -> browser captions + TTS ----
            # Translation tokens are accumulated per utterance and spoken when
            # the utterance closes (endpoint token), so TTS gets whole phrases.
            pending_speech = {"text": "", "lang": None}
            # Fallback boundary: if Soniox sends no endpoint marker, close an
            # utterance after this much quiet so boxes don't grow forever.
            last_token_at = {"t": None}
            IDLE_CLOSE = 1.2
            loop = asyncio.get_event_loop()

            async def speak_utterance():
                text = pending_speech["text"].strip()
                lang = pending_speech["lang"]
                pending_speech["text"] = ""
                pending_speech["lang"] = None
                if not (speak and text):
                    return
                await _tts_utterance(
                    text=text,
                    language=tts_lang_for(lang),
                    voice=voice,
                    to_browser=to_browser,
                )

            # Accumulate finalized text server-side, exactly like the working
            # transcription engine. Each Soniox payload carries the full set of
            # current non-final tokens, so partials are rebuilt every frame and
            # never accumulated. The browser receives the complete current text
            # and just displays it - no client-side concatenation.
            src_final = {"text": ""}
            tgt_final = {"text": ""}

            async def pump_stt():
                async for raw in stt:
                    payload = json.loads(raw)
                    if payload.get("error_code"):
                        await to_browser({
                            "type": "error",
                            "message": payload.get("error_message"),
                        })
                        continue

                    endpoint = bool(payload.get("is_endpoint") or payload.get("endpoint"))

                    # Rebuilt fresh from this payload's non-final tokens.
                    src_partial = ""
                    tgt_partial = ""

                    for tok in payload.get("tokens", []):
                        text = tok.get("text", "")
                        status = tok.get("translation_status")  # original|translation|none
                        lang = tok.get("language")

                        if DEBUG_TOKENS and text:
                            log.info("TOK status=%s lang=%s final=%s %r",
                                     status, lang, tok.get("is_final"), text)

                        if text in ("<end>", "<fin>") or tok.get("is_end") \
                                or tok.get("is_endpoint"):
                            endpoint = True
                            continue

                        if not text:
                            continue

                        is_final = bool(tok.get("is_final"))
                        if status == "translation":
                            if is_final:
                                tgt_final["text"] += text
                                pending_speech["text"] += text
                                if lang:
                                    pending_speech["lang"] = lang
                            else:
                                tgt_partial += text
                        else:
                            if is_final:
                                src_final["text"] += text
                            else:
                                src_partial += text

                        last_token_at["t"] = loop.time()

                    # Send the complete current text for each side. The browser
                    # replaces its box contents with this - no accumulation.
                    await to_browser({
                        "type": "captions",
                        "source": (src_final["text"] + src_partial).strip(),
                        "translation": (tgt_final["text"] + tgt_partial).strip(),
                    })

                    if endpoint:
                        await speak_utterance()
                        await to_browser({"type": "utterance_end"})
                        src_final["text"] = ""
                        tgt_final["text"] = ""

                # Stream closed: speak anything still buffered.
                await speak_utterance()

            async def idle_watchdog():
                # Close an utterance after a quiet gap, in case no endpoint
                # marker arrives. Sending utterance_end when nothing is pending
                # is harmless - the browser just has no open box to close.
                while True:
                    await asyncio.sleep(0.3)
                    t = last_token_at["t"]
                    if t is not None and (loop.time() - t) > IDLE_CLOSE:
                        last_token_at["t"] = None
                        await speak_utterance()
                        await to_browser({"type": "utterance_end"})

            watchdog_task = asyncio.create_task(idle_watchdog())
            try:
                await asyncio.gather(pump_mic(), pump_stt())
            except ConnectionClosedOK:
                pass
            finally:
                watchdog_task.cancel()

    except WebSocketDisconnect:
        log.info("translate client disconnected")
    except ConnectionClosedOK:
        pass
    except Exception as e:
        log.exception("translate bridge error")
        await to_browser({"type": "error", "message": str(e)})
    finally:
        alive = False
        try:
            await client.close()
        except Exception:
            pass


async def _fail(client, message):
    try:
        await client.send_json({"type": "error", "message": message})
        await client.close(code=4400)
    except Exception:
        pass


async def _tts_utterance(text, language, voice, to_browser):
    """Open one TTS stream, send the text, relay audio chunks to the browser.

    A fresh stream per utterance keeps latency low and avoids one long-lived
    TTS socket that could stall the whole session.
    """
    stream_id = f"u-{uuid.uuid4().hex[:8]}"
    try:
        async with connect(sx.TTS_WS_URL, max_size=None) as tts:
            await tts.send(json.dumps(
                sx.tts_config(voice=voice, language=language, stream_id=stream_id)
            ))
            await tts.send(json.dumps({"text": text, "stream_id": stream_id}))
            # Empty text closes the stream and flushes final audio.
            await tts.send(json.dumps({"text": "", "stream_id": stream_id}))

            await to_browser({
                "type": "audio_start",
                "sample_rate": sx.TTS_SAMPLE_RATE,
            })

            async for raw in tts:
                # TTS sends binary PCM frames, or JSON status/error frames.
                if isinstance(raw, (bytes, bytearray)):
                    await to_browser({
                        "type": "audio",
                        "pcm": base64.b64encode(bytes(raw)).decode("ascii"),
                    })
                    continue
                msg = json.loads(raw)
                if msg.get("error_code"):
                    await to_browser({
                        "type": "error",
                        "message": msg.get("error_message"),
                    })
                    break
                # Base64 audio delivered as JSON (some deployments do this).
                if msg.get("audio"):
                    await to_browser({"type": "audio", "pcm": msg["audio"]})
                if msg.get("finished") or msg.get("done"):
                    break

            await to_browser({"type": "audio_end"})
    except ConnectionClosedOK:
        await to_browser({"type": "audio_end"})
    except Exception as e:
        log.warning("tts stream failed: %s", e)
        await to_browser({"type": "error", "message": f"TTS failed: {e}"})