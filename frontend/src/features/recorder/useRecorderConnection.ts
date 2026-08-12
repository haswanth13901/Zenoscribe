import { useCallback, useEffect, useReducer, useRef } from "react";
import { useAppDispatch, useAppSelector } from "../../app/hooks";
import { clearCredentials } from "../auth/authSlice";
import { initialRecorderState, recorderReducer } from "./recorderReducer";
import type { ServerMessage } from "./types";

const WORKLET_URL = "/static/pcm-worklet.js";

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

  const teardown = useCallback(() => {
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
  }, []);

  const stop = useCallback(() => {
    dispatch({ type: "manual-stop" });
    teardown();
  }, [teardown]);

  const start = useCallback(() => {
    if (activeRef.current) return;
    activeRef.current = true;
    dispatch({ type: "start-requested" });

    void (async () => {
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: false },
        });
      } catch (err) {
        activeRef.current = false;
        dispatch({ type: "mic-denied", message: errorMessage(err) });
        return;
      }
      streamRef.current = stream;

      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${window.location.host}/ws`);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "auth", token }));
        dispatch({ type: "ws-open" });
      };

      ws.onmessage = (e: MessageEvent<string>) => {
        const m = JSON.parse(e.data) as ServerMessage;
        if (m.type === "ready") {
          dispatch({ type: "ws-ready" });
          void (async () => {
            try {
              const ctx = new AudioContext();
              await ctx.audioWorklet.addModule(WORKLET_URL);
              const node = new AudioWorkletNode(ctx, "pcm-worklet");
              ctx.createMediaStreamSource(stream).connect(node);
              node.port.onmessage = (ev: MessageEvent<ArrayBuffer>) => {
                if (ws.readyState === WebSocket.OPEN) ws.send(ev.data);
              };
              ctxRef.current = ctx;
              nodeRef.current = node;
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
  }, [token, teardown, reduxDispatch]);

  const clear = useCallback(() => dispatch({ type: "clear" }), []);

  // Cleanup on unmount - a real requirement now that leaving /app is a
  // client-side transition (e.g. clicking Home in the sidebar), not a full
  // page teardown like the vanilla version got for free.
  useEffect(() => teardown, [teardown]);

  return { state, start, stop, clear };
}
