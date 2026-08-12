import type { TranslateEvent, TranslateState, Utterance } from "./types";

export const initialTranslateState: TranslateState = {
  status: "idle",
  statusMessage: "idle",
  isError: false,
  utterances: [],
};

const ACTIVE_STATUSES = new Set(["connecting", "listening"]);

function upsertLast(utterances: Utterance[], patch: Partial<Utterance>, orNew: () => Utterance): Utterance[] {
  const last = utterances[utterances.length - 1];
  if (last && last.live) {
    return [...utterances.slice(0, -1), { ...last, ...patch }];
  }
  return [...utterances, orNew()];
}

// Pure state machine ported from translate.html's start()/stop()/restart()/
// ws.onmessage handlers, decoupled from the imperative WebSocket/
// AudioContext (mic capture AND TTS playback) side effects, which live in
// useTranslateConnection.ts. Unlike the recorder, there's no separate
// "authenticating" status: translate.py's hello frame carries auth+settings
// together, and the client shows nothing between "connecting" and
// "listening" - confirmed against the original page's own status text.
export function translateReducer(state: TranslateState, event: TranslateEvent): TranslateState {
  switch (event.type) {
    case "start-requested":
      if (ACTIVE_STATUSES.has(state.status)) return state;
      return { ...state, status: "connecting", statusMessage: "connecting", isError: false };

    case "mic-denied":
      return { ...state, status: "stopped", statusMessage: `mic error: ${event.message}`, isError: true };

    case "ws-open":
    case "ws-ready":
      // No visible transition - matches the original having no status text
      // between sending the hello frame and either "ready" (mic setup,
      // handled by audio-ready/audio-fail) or an error/close.
      return state;

    case "audio-ready":
      return { ...state, status: "listening", statusMessage: "listening", isError: false };

    case "audio-fail":
      return { ...state, status: "stopped", statusMessage: `audio setup failed: ${event.message}`, isError: true };

    case "captions": {
      const { source, translation, speaker, language, ts } = event;
      return {
        ...state,
        utterances: upsertLast(
          state.utterances,
          { source, translation, speaker, language },
          () => ({ speaker, language, spokenLang: null, source, translation, live: true, ts }),
        ),
      };
    }

    case "audio-start": {
      // Sent while the utterance it belongs to is still the client's "live"
      // one - speak_utterance() is awaited before utterance_end is sent, so
      // ordering guarantees the last entry is the right target. A no-op if
      // there's no live utterance or no language given, matching the
      // original's `if (tgtHolder.el && m.language)` guard.
      if (!event.language) return state;
      const last = state.utterances[state.utterances.length - 1];
      if (!last || !last.live) return state;
      return {
        ...state,
        utterances: [...state.utterances.slice(0, -1), { ...last, spokenLang: event.language }],
      };
    }

    case "utterance-end": {
      const last = state.utterances[state.utterances.length - 1];
      if (!last) return state;
      // Only overwrite language/speaker if provided - the idle_watchdog
      // fallback path sends a bare utterance_end with neither field, and
      // the original's closeUtterance() only stamps when truthy.
      const updated: Utterance = {
        ...last,
        live: false,
        language: event.language ?? last.language,
        speaker: event.speaker ?? last.speaker,
      };
      return { ...state, utterances: [...state.utterances.slice(0, -1), updated] };
    }

    case "server-error":
      return { ...state, status: "stopped", statusMessage: `error: ${event.message}`, isError: true };

    case "timeout":
      return {
        ...state,
        status: "stopped",
        statusMessage: event.message || "Session ended after inactivity.",
        isError: false,
      };

    case "ws-close":
      if (!ACTIVE_STATUSES.has(state.status)) return state;
      // Deliberate improvement over the original (same fix already applied
      // to the recorder): it only called stop() if `running` was already
      // true, so a close during "connecting" left the toggle stuck. Any
      // active status now recovers to "stopped".
      return { ...state, status: "stopped", statusMessage: "stopped", isError: false };

    case "ws-error":
      return { ...state, status: "stopped", statusMessage: "connection failed", isError: true };

    case "manual-stop":
      if (!ACTIVE_STATUSES.has(state.status)) return state;
      return { ...state, status: "stopped", statusMessage: "stopped", isError: false };

    case "restart-started":
      return { ...state, statusMessage: "restarting", isError: false };

    case "restart-cleared":
      return { ...state, statusMessage: "cleared", isError: false };

    case "clear":
      // Independent of status, matching the original clearTranscript() not
      // checking `running`.
      return { ...state, utterances: [] };

    default:
      return state;
  }
}
