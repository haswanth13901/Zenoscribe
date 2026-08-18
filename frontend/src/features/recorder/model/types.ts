export interface Turn {
  speaker: string;
  text: string;
  start: number | null;
}

export interface PartialTurn {
  speaker: string;
  text: string;
}

export type RecorderStatus = "idle" | "connecting" | "authenticating" | "listening" | "stopped";

export interface RecorderState {
  status: RecorderStatus;
  /** Human-readable status text shown in the header, e.g. "listening",
   * "error: <message>", "mic error: <message>" - ported verbatim from the
   * original page's #status text assignments. */
  statusMessage: string;
  isError: boolean;
  turns: Turn[];
  partial: PartialTurn | null;
  /** True while actively listening and the tab is backgrounded/screen
   * locked - mobile browsers may suspend JS/audio in this state, so the UI
   * warns the recording could silently stop. Cleared as soon as the tab is
   * visible again, regardless of status. */
  backgrounded: boolean;
  /** True while the WS dropped unexpectedly (not a manual stop, not an
   * auth failure) and useRecorderConnection is retrying with backoff. The
   * mic stream and AudioWorklet stay alive underneath - only the socket is
   * being recreated. */
  reconnecting: boolean;
}

// The /ws server's message shapes (transcribe.py) - trusted, not runtime
// validated, matching how the rest of this codebase treats API responses.
export type ServerMessage =
  | { type: "ready" }
  | { type: "final"; speaker: string; text: string; start: number | null }
  | { type: "partial"; speaker: string; text: string }
  | { type: "error"; message: string };

export type RecorderEvent =
  | { type: "start-requested" }
  | { type: "mic-denied"; message: string }
  | { type: "ws-open" }
  | { type: "ws-ready" }
  | { type: "audio-ready" }
  | { type: "audio-fail"; message: string }
  | { type: "final"; speaker: string; text: string; start: number | null }
  | { type: "partial"; speaker: string; text: string }
  | { type: "server-error"; message: string }
  | { type: "ws-close" }
  | { type: "ws-error" }
  | { type: "manual-stop" }
  | { type: "clear" }
  | { type: "tab-hidden" }
  | { type: "tab-visible" }
  | { type: "reconnect-scheduled"; attempt: number }
  | { type: "reconnected" };
