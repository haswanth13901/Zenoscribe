export interface Utterance {
  speaker: string | null;
  /** Detected/spoken source language for this utterance (lang_votes winner). */
  language: string | null;
  /** The TTS audio's actual spoken language, stamped from audio_start. */
  spokenLang: string | null;
  source: string;
  translation: string;
  live: boolean;
  /** Set once, when this utterance is first created - matches the original
   * stamping `data-ts` only on creation, never touching it again. */
  ts: number;
}

export type TranslateStatus = "idle" | "connecting" | "listening" | "stopped";

export interface TranslateState {
  status: TranslateStatus;
  /** Human-readable status text shown in the header, ported verbatim from
   * the original page's #status text assignments (plus "restarting"/
   * "cleared" for Restart's two branches). */
  statusMessage: string;
  isError: boolean;
  /** Last entry may have live:true (still in progress); everything before
   * it is finalized. Index-based keys are safe for rendering since entries
   * are only ever appended or wiped (clear), never reordered. */
  utterances: Utterance[];
}

export type TranslateMode = "one_way" | "two_way";

export interface TranslateSettings {
  mode: TranslateMode;
  speak: boolean;
  voice: string;
  diarize: boolean;
  /** Optional hint for how many distinct voices to expect; only sent to
   * Soniox when diarize is on. */
  numSpeakers?: number;
  /** one_way only. */
  targetLanguage: string;
  /** two_way only. */
  languageA: string;
  /** two_way only. */
  languageB: string;
}

// The /ws/translate server's message shapes (translate.py) - trusted, not
// runtime validated, matching how the rest of this codebase treats API
// responses.
export type ServerMessage =
  | { type: "ready" }
  | {
      type: "captions";
      source: string;
      translation: string;
      speaker: string | null;
      language: string | null;
    }
  | { type: "audio_start"; sample_rate: number; language: string | null }
  | { type: "audio"; pcm: string }
  | { type: "audio_end" }
  | { type: "utterance_end"; speaker?: string | null; language?: string | null }
  | { type: "timeout"; message?: string }
  | { type: "error"; message: string };

export type TranslateEvent =
  | { type: "start-requested" }
  | { type: "mic-denied"; message: string }
  | { type: "ws-open" }
  | { type: "ws-ready" }
  | { type: "audio-ready" }
  | { type: "audio-fail"; message: string }
  | {
      type: "captions";
      source: string;
      translation: string;
      speaker: string | null;
      language: string | null;
      ts: number;
    }
  | { type: "audio-start"; language: string | null }
  | { type: "utterance-end"; speaker?: string | null; language?: string | null }
  | { type: "server-error"; message: string }
  | { type: "timeout"; message?: string }
  | { type: "ws-close" }
  | { type: "ws-error" }
  | { type: "manual-stop" }
  | { type: "restart-started" }
  | { type: "restart-cleared" }
  | { type: "clear" };
