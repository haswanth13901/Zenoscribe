import { useCallback, useEffect, useReducer, useRef } from "react";
import { useAppDispatch, useAppSelector } from "@/app/hooks";
import { clearCredentials } from "@/features/auth/model/authSlice";
import { initialRecorderState, recorderReducer } from "@/features/recorder/model/recorderReducer";
import type { ServerMessage } from "@/features/recorder/model/types";
import { useDocumentHidden } from "@/shared/lib/useDocumentHidden";
import { MAX_RECONNECT_ATTEMPTS, reconnectDelayMs } from "@/shared/lib/reconnectBackoff";
import { AUDIO_WORKLET_UNSUPPORTED_MESSAGE } from "@/shared/lib/browserSupport";

const WORKLET_URL = `${import.meta.env.BASE_URL}pcm-worklet.js`;

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

// Imperative side-effect layer around recorderReducer: owns the WebSocket,
// AudioContext, AudioWorkletNode and MediaStream, ported from index.html's
// start()/stop() (see the plan for the exact line-by-line mapping). Every
// state transition goes through the pure reducer; this hook's only job is
// to drive the browser APIs and translate their callbacks into events.
export function useRecorderConnection() {
  const [state, dispatch] = useReducer(recorderReducer, initialRecorderState);
  const token = useAppSelector((s) => s.auth.token);
  const reduxDispatch = useAppDispatch();

  const wsRef = useRef<WebSocket | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const nodeRef = useRef<AudioWorkletNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  // True once start() has begun and not yet fully torn down - guards
  // against a second Start click spinning up a duplicate connection.
  const activeRef = useRef(false);
  // Set right before we close a socket ourselves (manual stop, a server
  // error frame, giving up after max reconnect attempts) so that socket's
  // own onclose handler knows not to treat the closure as a drop worth
  // retrying.
  const intentionalCloseRef = useRef(false);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const teardown = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    intentionalCloseRef.current = true;
    if (nodeRef.current) {
      nodeRef.current.disconnect();
      nodeRef.current = null;
    }
    if (ctxRef.current) {
      void ctxRef.current.close().catch(() => {});
      ctxRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
      wsRef.current.close();
    }
    wsRef.current = null;
    activeRef.current = false;
    reconnectAttemptsRef.current = 0;
  }, []);

  const stop = useCallback(() => {
    dispatch({ type: "manual-stop" });
    teardown();
  }, [teardown]);

  const start = useCallback((numSpeakers?: number) => {
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

      // Opens (or reopens, after a drop) the /ws socket. The mic stream and,
      // once set up, the AudioContext/AudioWorkletNode are created once and
      // reused across reconnects - only the socket itself gets recreated,
      // via a fresh call to this function from the onclose backoff timer.
      const connect = () => {
        const proto = window.location.protocol === "https:" ? "wss" : "ws";
        const ws = new WebSocket(`${proto}://${window.location.host}/ws`);
        ws.binaryType = "arraybuffer";
        wsRef.current = ws;
        intentionalCloseRef.current = false;

        ws.onopen = () => {
          ws.send(JSON.stringify({ type: "auth", token, num_speakers: numSpeakers }));
          dispatch({ type: "ws-open" });
        };

        ws.onmessage = (e: MessageEvent<string>) => {
          const m = JSON.parse(e.data) as ServerMessage;
          if (m.type === "ready") {
            if (ctxRef.current) {
              // Audio pipeline already exists from before the drop - this
              // "ready" is the server confirming the reconnected socket,
              // not a first-time setup.
              reconnectAttemptsRef.current = 0;
              dispatch({ type: "reconnected" });
              return;
            }
            dispatch({ type: "ws-ready" });
            void (async () => {
              try {
                const ctx = new AudioContext();
                if (!ctx.audioWorklet) throw new Error(AUDIO_WORKLET_UNSUPPORTED_MESSAGE);
                await ctx.audioWorklet.addModule(WORKLET_URL);
                const node = new AudioWorkletNode(ctx, "pcm-worklet");
                ctx.createMediaStreamSource(stream).connect(node);
                // Reads wsRef.current (not the `ws` created above) on every
                // frame, so audio keeps flowing to whichever socket is
                // currently live across reconnects instead of hanging onto
                // this specific (possibly since-replaced) instance.
                node.port.onmessage = (ev: MessageEvent<ArrayBuffer>) => {
                  const socket = wsRef.current;
                  if (socket && socket.readyState === WebSocket.OPEN) socket.send(ev.data);
                };
                ctxRef.current = ctx;
                nodeRef.current = node;
                reconnectAttemptsRef.current = 0;
                dispatch({ type: "audio-ready" });
              } catch (err) {
                dispatch({ type: "audio-fail", message: errorMessage(err) });
                teardown();
              }
            })();
            return;
          }
          if (m.type === "final") {
            dispatch({ type: "final", speaker: m.speaker, text: m.text, start: m.start ?? null });
          } else if (m.type === "partial") {
            dispatch({ type: "partial", speaker: m.speaker, text: m.text });
          } else if (m.type === "error") {
            dispatch({ type: "server-error", message: m.message });
            teardown();
          }
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
  }, [token, teardown, reduxDispatch]);

  const clear = useCallback(() => dispatch({ type: "clear" }), []);

  // Cleanup on unmount - a real requirement now that leaving /app is a
  // client-side transition (e.g. clicking Home in the sidebar), not a full
  // page teardown like the vanilla version got for free.
  useEffect(() => teardown, [teardown]);

  // Warn while backgrounded during an active session (see recorderReducer's
  // tab-hidden/tab-visible cases) - mobile browsers may suspend the WS/audio
  // pipeline in this state, so a session that dies there would otherwise
  // look like a silent hang rather than something the user could avoid.
  const isHidden = useDocumentHidden();
  useEffect(() => {
    dispatch({ type: isHidden ? "tab-hidden" : "tab-visible" });
  }, [isHidden, state.status]);

  return { state, start, stop, clear };
}
