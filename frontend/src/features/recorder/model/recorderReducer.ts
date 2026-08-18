import type { RecorderEvent, RecorderState } from "@/features/recorder/model/types";

export const initialRecorderState: RecorderState = {
  status: "idle",
  statusMessage: "idle",
  isError: false,
  turns: [],
  partial: null,
  backgrounded: false,
  reconnecting: false,
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
      // Guarded on "connecting" (not just ACTIVE_STATUSES) because this
      // also fires when a reconnect attempt's socket opens, and status
      // stays "listening" throughout a reconnect (see reconnect-scheduled)
      // - without the guard, a reconnect's ws-open would incorrectly knock
      // status back down to "authenticating" mid-session.
      if (state.status !== "connecting") return state;
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
        reconnecting: false,
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
        reconnecting: false,
      };

    case "ws-close":
      if (!ACTIVE_STATUSES.has(state.status)) return state;
      // Deliberate improvement over the original: it only called stop() on
      // close if `running` was already true, so a close during
      // "connecting"/"authenticating" (before the WS ever reached
      // "listening") left the toggle permanently disabled. Any active
      // status now recovers to "stopped". Reached today only after
      // reconnect attempts are exhausted (see reconnect-scheduled) - a
      // single drop retries first instead of landing here immediately.
      return {
        ...state,
        status: "stopped",
        statusMessage: "stopped",
        isError: false,
        partial: null,
        reconnecting: false,
      };

    case "ws-error":
      return {
        ...state,
        status: "stopped",
        statusMessage: "connection failed",
        isError: true,
        partial: null,
        reconnecting: false,
      };

    case "manual-stop":
      if (!ACTIVE_STATUSES.has(state.status)) return state;
      return {
        ...state,
        status: "stopped",
        statusMessage: "stopped",
        isError: false,
        partial: null,
        reconnecting: false,
      };

    case "clear":
      // Independent of status, matching the original #clear handler (it
      // doesn't check `running`).
      return { ...state, turns: [], partial: null };

    case "tab-hidden":
      // Only worth warning about while a session is actually live - a
      // backgrounded idle/stopped page has nothing to lose.
      if (state.status !== "listening" || state.backgrounded) return state;
      return { ...state, backgrounded: true };

    case "tab-visible":
      if (!state.backgrounded) return state;
      return { ...state, backgrounded: false };

    case "reconnect-scheduled":
      // status is deliberately left as-is (still "listening"/"connecting"/
      // "authenticating") - the mic/AudioWorklet are still alive underneath,
      // only the socket dropped, so Stop must stay available throughout.
      if (!ACTIVE_STATUSES.has(state.status)) return state;
      return {
        ...state,
        reconnecting: true,
        statusMessage: `reconnecting (attempt ${event.attempt})…`,
        isError: false,
      };

    case "reconnected":
      return {
        ...state,
        status: "listening",
        statusMessage: "listening",
        isError: false,
        reconnecting: false,
      };

    default:
      return state;
  }
}
