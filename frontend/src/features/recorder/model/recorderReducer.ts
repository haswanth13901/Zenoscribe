import type { RecorderEvent, RecorderState } from "@/features/recorder/model/types";

export const initialRecorderState: RecorderState = {
  status: "idle",
  statusMessage: "idle",
  isError: false,
  turns: [],
  partial: null,
};

const ACTIVE_STATUSES = new Set(["connecting", "authenticating", "listening"]);

// Pure state machine ported from index.html's start()/stop()/ws.onmessage
// handlers, decoupled from the imperative WebSocket/AudioContext/
// AudioWorklet side effects (those live in useRecorderConnection.ts) so
// this transition logic is unit-testable without mocking real browser APIs.
export function recorderReducer(state: RecorderState, event: RecorderEvent): RecorderState {
  switch (event.type) {
    case "start-requested":
      // Mirrors the original's `if (running || connecting) return;` guard.
      if (ACTIVE_STATUSES.has(state.status)) return state;
      return { ...state, status: "connecting", statusMessage: "connecting", isError: false };

    case "mic-denied":
      return {
        ...state,
        status: "stopped",
        statusMessage: `mic error: ${event.message}`,
        isError: true,
      };

    case "ws-open":
      return { ...state, status: "authenticating", statusMessage: "authenticating" };

    case "ws-ready":
      // No visible transition yet - audio setup runs next, invisibly, in
      // the hook; only audio-ready/audio-fail move the status forward,
      // matching the original having no UI state between "authenticating"
      // and "listening".
      return state;

    case "audio-ready":
      return { ...state, status: "listening", statusMessage: "listening", isError: false };

    case "audio-fail":
      return {
        ...state,
        status: "stopped",
        statusMessage: `audio setup failed: ${event.message}`,
        isError: true,
        partial: null,
      };

    case "final":
      return {
        ...state,
        turns: [...state.turns, { speaker: event.speaker, text: event.text, start: event.start }],
        partial: null,
      };

    case "partial":
      // Replaces, not appends - Soniox resends the full hypothesis each
      // frame, matching the original showPartial().
      return { ...state, partial: { speaker: event.speaker, text: event.text } };

    case "server-error":
      return {
        ...state,
        status: "stopped",
        statusMessage: `error: ${event.message}`,
        isError: true,
        partial: null,
      };

    case "ws-close":
      if (!ACTIVE_STATUSES.has(state.status)) return state;
      // Deliberate improvement over the original: it only called stop() on
      // close if `running` was already true, so a close during
      // "connecting"/"authenticating" (before the WS ever reached
      // "listening") left the toggle permanently disabled. Any active
      // status now recovers to "stopped".
      return {
        ...state,
        status: "stopped",
        statusMessage: "stopped",
        isError: false,
        partial: null,
      };

    case "ws-error":
      return {
        ...state,
        status: "stopped",
        statusMessage: "connection failed",
        isError: true,
        partial: null,
      };

    case "manual-stop":
      if (!ACTIVE_STATUSES.has(state.status)) return state;
      return {
        ...state,
        status: "stopped",
        statusMessage: "stopped",
        isError: false,
        partial: null,
      };

    case "clear":
      // Independent of status, matching the original #clear handler (it
      // doesn't check `running`).
      return { ...state, turns: [], partial: null };

    default:
      return state;
  }
}
