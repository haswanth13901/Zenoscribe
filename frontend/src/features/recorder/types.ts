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
  | { type: "clear" };
