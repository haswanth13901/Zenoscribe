import { useCallback, useEffect, useReducer, useRef } from "react";
import { useAppDispatch, useAppSelector } from "@/app/hooks";
import { clearCredentials } from "@/features/auth/model/authSlice";
import {
  initialTranslateState,
  translateReducer,
} from "@/features/translate/model/translateReducer";
import type { ServerMessage, TranslateSettings } from "@/features/translate/model/types";
import { useDocumentHidden } from "@/shared/lib/useDocumentHidden";
import { MAX_RECONNECT_ATTEMPTS, reconnectDelayMs } from "@/shared/lib/reconnectBackoff";
import { AUDIO_WORKLET_UNSUPPORTED_MESSAGE } from "@/shared/lib/browserSupport";

const WORKLET_URL = `${import.meta.env.BASE_URL}pcm-worklet.js`;

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function buildHello(token: string | null, settings: TranslateSettings) {
  const base = {
    token,
    speak: settings.speak,
    voice: settings.voice,
    diarize: settings.diarize,
    num_speakers: settings.numSpeakers,
    mode: settings.mode,
  };
  if (settings.mode === "one_way") {
    return { ...base, target_language: settings.targetLanguage };
  }
  return { ...base, language_a: settings.languageA, language_b: settings.languageB };
}

// Imperative side-effect layer around translateReducer: owns the
// WebSocket, the mic-capture AudioContext (identical wiring to the
// recorder's useRecorderConnection.ts) and a second TTS-playback
// AudioContext with zero precedent elsewhere in this codebase. Ported from
// translate.html's start()/stop()/restart() (see the plan for the exact
// mapping), fixing the two real bugs found while reading the source: no
// double-start guard, and an unhandled rejection if mic setup fails inside
// the "ready" handler.
//
// translate.html has no standalone "Clear" button (only Restart, which
// clears as part of its own sequence) - `clear` is a reducer event used
// internally by restart(), not exposed here, since nothing else needs it.
export function useTranslateConnection() {
  const [state, dispatch] = useReducer(translateReducer, initialTranslateState);
  const token = useAppSelector((s) => s.auth.token);
  const reduxDispatch = useAppDispatch();

  const wsRef = useRef<WebSocket | null>(null);
  const micCtxRef = useRef<AudioContext | null>(null);
  const micNodeRef = useRef<AudioWorkletNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const playCtxRef = useRef<AudioContext | null>(null);
  const playHeadRef = useRef(0);
  const ttsSampleRateRef = useRef<number | null>(null);
  // True once start() has begun and not yet fully torn down - fixes bug #1
  // (the original had no equivalent guard, so a second Start click during
  // the "connecting" window opened a second WebSocket + getUserMedia call).
  const activeRef = useRef(false);
  // Set right before we close a socket ourselves (manual stop/restart, an
  // idle-watchdog timeout, a server error frame, giving up after max
  // reconnect attempts) so that socket's own onclose handler knows not to
  // treat the closure as a drop worth retrying.
  const intentionalCloseRef = useRef(false);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const playAudioChunk = useCallback((base64: string, sampleRate: number) => {
    // The context itself is created (and resumed) synchronously in start(),
    // inside the click handler - see the comment there for why. It isn't
    // recreated per utterance, so the gapless playHead cursor stays valid
    // across them.
    const ac = playCtxRef.current;
    if (!ac) return;
    const bin = atob(base64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const view = new DataView(bytes.buffer);
    const n = Math.floor(bytes.length / 2);
    // Buffer is declared at the source's own sample rate, not the context's
    // - the AudioBufferSourceNode resamples to ac.sampleRate automatically
    // on playback, so this plays at correct pitch/speed regardless of what
    // rate the context actually ended up running at.
    const buffer = ac.createBuffer(1, n, sampleRate);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < n; i++) channel[i] = view.getInt16(i * 2, true) / 32768;
    const srcNode = ac.createBufferSource();
    srcNode.buffer = buffer;
    srcNode.connect(ac.destination);
    const now = ac.currentTime;
    if (playHeadRef.current < now) playHeadRef.current = now;
    srcNode.start(playHeadRef.current);
    playHeadRef.current += buffer.duration;
  }, []);

  const teardown = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    intentionalCloseRef.current = true;
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ eof: true }));
      } catch {
        // Best effort.
      }
    }
    if (micNodeRef.current) {
      micNodeRef.current.disconnect();
      micNodeRef.current = null;
    }
    if (micCtxRef.current) {
      void micCtxRef.current.close().catch(() => {});
      micCtxRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (playCtxRef.current) {
      // Stop any queued TTS audio so it doesn't keep speaking after Stop/Restart.
      try {
        playCtxRef.current.close();
      } catch {
        // Ignore.
      }
      playCtxRef.current = null;
    }
    playHeadRef.current = 0;
    ttsSampleRateRef.current = null;
    if (ws) {
      // Delay matches the original's 300ms setTimeout before closing the WS,
      // giving the {eof:true} frame time to flush.
      setTimeout(() => {
        if (ws.readyState === WebSocket.OPEN) ws.close();
      }, 300);
    }
    wsRef.current = null;
    activeRef.current = false;
    reconnectAttemptsRef.current = 0;
  }, []);

  const stop = useCallback(() => {
    dispatch({ type: "manual-stop" });
    teardown();
  }, [teardown]);

  const start = useCallback(
    (settings: TranslateSettings) => {
      if (activeRef.current) return;
      activeRef.current = true;
      dispatch({ type: "start-requested" });

      if (settings.speak) {
        // Created + resumed synchronously here, inside the click handler,
        // rather than lazily inside playAudioChunk (which only runs off an
        // async WebSocket message). Mobile Safari's autoplay policy only
        // unlocks audio output for a context that is created or resumed
        // within the actual user-gesture call stack; one spun up later from
        // a network callback stays suspended and plays nothing.
        const playCtx = new AudioContext();
        playCtxRef.current = playCtx;
        void playCtx.resume().catch(() => {});
      }

      void (async () => {
        let stream: MediaStream;
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            audio: {
              channelCount: 1,
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: false,
            },
          });
        } catch (err) {
          activeRef.current = false;
          dispatch({ type: "mic-denied", message: errorMessage(err) });
          return;
        }
        streamRef.current = stream;

        // Opens (or reopens, after a drop) the /ws/translate socket. The
        // mic stream and, once set up, the AudioContext/AudioWorkletNode
        // are created once and reused across reconnects - only the socket
        // itself gets recreated, via a fresh call to this function from the
        // onclose backoff timer.
        const connect = () => {
          const proto = window.location.protocol === "https:" ? "wss" : "ws";
          const ws = new WebSocket(`${proto}://${window.location.host}/ws/translate`);
          ws.binaryType = "arraybuffer";
          wsRef.current = ws;
          intentionalCloseRef.current = false;

          ws.onopen = () => {
            ws.send(JSON.stringify(buildHello(token, settings)));
            dispatch({ type: "ws-open" });
          };

          ws.onmessage = (e: MessageEvent<string>) => {
            const m = JSON.parse(e.data) as ServerMessage;
            if (m.type === "ready") {
              if (micCtxRef.current) {
                // Mic pipeline already exists from before the drop - this
                // "ready" is the server confirming the reconnected socket,
                // not a first-time setup.
                reconnectAttemptsRef.current = 0;
                dispatch({ type: "reconnected" });
                return;
              }
              dispatch({ type: "ws-ready" });
              void (async () => {
                // Bug #2 fix: the original had no try/catch here, so a
                // rejection (e.g. addModule failing) was a silent unhandled
                // promise rejection with no recovery path.
                try {
                  const ctx = new AudioContext();
                  if (!ctx.audioWorklet) throw new Error(AUDIO_WORKLET_UNSUPPORTED_MESSAGE);
                  await ctx.audioWorklet.addModule(WORKLET_URL);
                  const node = new AudioWorkletNode(ctx, "pcm-worklet");
                  ctx.createMediaStreamSource(stream).connect(node);
                  // Reads wsRef.current (not the `ws` created above) on
                  // every frame, so audio keeps flowing to whichever socket
                  // is currently live across reconnects instead of hanging
                  // onto this specific (possibly since-replaced) instance.
                  node.port.onmessage = (ev: MessageEvent<ArrayBuffer>) => {
                    const socket = wsRef.current;
                    if (socket && socket.readyState === WebSocket.OPEN) socket.send(ev.data);
                  };
                  micCtxRef.current = ctx;
                  micNodeRef.current = node;
                  reconnectAttemptsRef.current = 0;
                  dispatch({ type: "audio-ready" });
                } catch (err) {
                  dispatch({ type: "audio-fail", message: errorMessage(err) });
                  teardown();
                }
              })();
              return;
            }
            if (m.type === "captions") {
              dispatch({
                type: "captions",
                source: m.source,
                translation: m.translation,
                speaker: m.speaker,
                language: m.language,
                ts: Date.now(),
              });
            } else if (m.type === "audio_start") {
              ttsSampleRateRef.current = m.sample_rate;
              dispatch({ type: "audio-start", language: m.language });
            } else if (m.type === "audio") {
              playAudioChunk(m.pcm, ttsSampleRateRef.current ?? 24000);
            } else if (m.type === "utterance_end") {
              dispatch({ type: "utterance-end", speaker: m.speaker, language: m.language });
            } else if (m.type === "timeout") {
              dispatch({ type: "timeout", message: m.message });
              teardown();
            } else if (m.type === "error") {
              dispatch({ type: "server-error", message: m.message });
              teardown();
            } else if (m.type === "tts_error") {
              // Scoped to one utterance's spoken-audio stream - the live
              // session (captions, mic) keeps going even if this one
              // sentence couldn't be spoken aloud.
              console.warn("translate: TTS failed for one utterance:", m.message);
            }
            // audio_end: no-op, matches the original (no handler for it either).
          };

          ws.onclose = (ev: CloseEvent) => {
            wsRef.current = null;
            if (intentionalCloseRef.current) return;
            if (ev.code === 4401) {
              reduxDispatch(clearCredentials());
              window.location.href = "/login";
              return;
            }
            const attempt = reconnectAttemptsRef.current + 1;
            if (attempt > MAX_RECONNECT_ATTEMPTS) {
              dispatch({ type: "ws-close" });
              teardown();
              return;
            }
            reconnectAttemptsRef.current = attempt;
            dispatch({ type: "reconnect-scheduled", attempt });
            reconnectTimerRef.current = setTimeout(connect, reconnectDelayMs(attempt));
          };

          ws.onerror = () => {
            // A WebSocket that errors always also fires close per spec, and
            // only the close event carries the code needed to tell an auth
            // rejection from a network drop - the reconnect decision lives
            // entirely in onclose above.
          };
        };

        connect();
      })();
    },
    [token, teardown, playAudioChunk, reduxDispatch],
  );

  const restart = useCallback(
    (settings: TranslateSettings) => {
      const wasRunning = activeRef.current;
      if (wasRunning) stop();
      dispatch({ type: "clear" });
      if (wasRunning) {
        dispatch({ type: "restart-started" });
        setTimeout(() => start(settings), 400);
      } else {
        dispatch({ type: "restart-cleared" });
      }
    },
    [stop, start],
  );

  // Cleanup on unmount - a real requirement now that leaving /translate is
  // a client-side transition, not a full page teardown.
  useEffect(() => teardown, [teardown]);

  // Warn while backgrounded during an active session (see translateReducer's
  // tab-hidden/tab-visible cases) - mobile browsers may suspend the WS/audio
  // pipeline in this state, so a session that dies there would otherwise
  // look like a silent hang rather than something the user could avoid.
  const isHidden = useDocumentHidden();
  useEffect(() => {
    dispatch({ type: isHidden ? "tab-hidden" : "tab-visible" });
  }, [isHidden, state.status]);

  return { state, start, stop, restart };
}
