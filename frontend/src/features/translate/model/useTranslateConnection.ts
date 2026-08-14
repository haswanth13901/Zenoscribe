import { useCallback, useEffect, useReducer, useRef } from "react";
import { useAppDispatch, useAppSelector } from "@/app/hooks";
import { clearCredentials } from "@/features/auth/model/authSlice";
import {
  initialTranslateState,
  translateReducer,
} from "@/features/translate/model/translateReducer";
import type { ServerMessage, TranslateSettings } from "@/features/translate/model/types";

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

  const playAudioChunk = useCallback((base64: string, sampleRate: number) => {
    // One AudioContext for the whole session, created lazily at the first
    // chunk's rate - matches ensurePlayCtx() exactly (not recreated per
    // utterance, so the gapless playHead cursor stays valid across them).
    if (!playCtxRef.current) {
      playCtxRef.current = new AudioContext({ sampleRate });
    }
    const ac = playCtxRef.current;
    const bin = atob(base64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const view = new DataView(bytes.buffer);
    const n = Math.floor(bytes.length / 2);
    const buffer = ac.createBuffer(1, n, ac.sampleRate);
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

        const proto = window.location.protocol === "https:" ? "wss" : "ws";
        const ws = new WebSocket(`${proto}://${window.location.host}/ws/translate`);
        ws.binaryType = "arraybuffer";
        wsRef.current = ws;

        ws.onopen = () => {
          ws.send(JSON.stringify(buildHello(token, settings)));
          dispatch({ type: "ws-open" });
        };

        ws.onmessage = (e: MessageEvent<string>) => {
          const m = JSON.parse(e.data) as ServerMessage;
          if (m.type === "ready") {
            dispatch({ type: "ws-ready" });
            void (async () => {
              // Bug #2 fix: the original had no try/catch here, so a
              // rejection (e.g. addModule failing) was a silent unhandled
              // promise rejection with no recovery path.
              try {
                const ctx = new AudioContext();
                await ctx.audioWorklet.addModule(WORKLET_URL);
                const node = new AudioWorkletNode(ctx, "pcm-worklet");
                ctx.createMediaStreamSource(stream).connect(node);
                node.port.onmessage = (ev: MessageEvent<ArrayBuffer>) => {
                  if (ws.readyState === WebSocket.OPEN) ws.send(ev.data);
                };
                micCtxRef.current = ctx;
                micNodeRef.current = node;
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
          }
          // audio_end: no-op, matches the original (no handler for it either).
        };

        ws.onclose = (ev: CloseEvent) => {
          if (ev.code === 4401) {
            reduxDispatch(clearCredentials());
            window.location.href = "/login";
            return;
          }
          dispatch({ type: "ws-close" });
          teardown();
        };

        ws.onerror = () => {
          dispatch({ type: "ws-error" });
          teardown();
        };
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

  return { state, start, stop, restart };
}
