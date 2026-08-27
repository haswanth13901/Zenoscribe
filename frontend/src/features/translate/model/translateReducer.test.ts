import { describe, expect, it } from "vitest";
import {
  initialTranslateState,
  translateReducer,
} from "@/features/translate/model/translateReducer";
import type { TranslateState } from "@/features/translate/model/types";

describe("translateReducer", () => {
  it("starts idle", () => {
    expect(initialTranslateState.status).toBe("idle");
    expect(initialTranslateState.utterances).toEqual([]);
  });

  it("start-requested moves to connecting and is a no-op while already active", () => {
    let state = translateReducer(initialTranslateState, { type: "start-requested" });
    expect(state.status).toBe("connecting");
    expect(state.isError).toBe(false);

    const afterFirst = state;
    state = translateReducer(state, { type: "start-requested" });
    expect(state).toBe(afterFirst);
  });

  it("has no distinct authenticating state - ws-open/ws-ready are no-ops", () => {
    let state = translateReducer(initialTranslateState, { type: "start-requested" });
    const afterStart = state;
    state = translateReducer(state, { type: "ws-open" });
    expect(state).toBe(afterStart);
    state = translateReducer(state, { type: "ws-ready" });
    expect(state).toBe(afterStart);
  });

  it("audio-ready moves to listening", () => {
    let state = translateReducer(initialTranslateState, { type: "start-requested" });
    state = translateReducer(state, { type: "audio-ready" });
    expect(state.status).toBe("listening");
    expect(state.statusMessage).toBe("listening");
    expect(state.isError).toBe(false);
  });

  it("mic-denied and audio-fail stop with the exact original message formats", () => {
    const micDenied = translateReducer(initialTranslateState, {
      type: "mic-denied",
      message: "Permission denied",
    });
    expect(micDenied.status).toBe("stopped");
    expect(micDenied.statusMessage).toBe("mic error: Permission denied");
    expect(micDenied.isError).toBe(true);

    const audioFail = translateReducer(
      { ...initialTranslateState, status: "connecting" },
      { type: "audio-fail", message: "boom" },
    );
    expect(audioFail.status).toBe("stopped");
    expect(audioFail.statusMessage).toBe("audio setup failed: boom");
    expect(audioFail.isError).toBe(true);
  });

  describe("captions", () => {
    it("creates a new live utterance when none is in progress", () => {
      const state = translateReducer(initialTranslateState, {
        type: "captions",
        source: "hola",
        translation: "hello",
        speaker: "user-1",
        language: "es",
        ts: 1000,
      });
      expect(state.utterances).toEqual([
        {
          speaker: "user-1",
          language: "es",
          spokenLang: null,
          source: "hola",
          translation: "hello",
          live: true,
          ts: 1000,
        },
      ]);
    });

    it("replaces (not appends) the live utterance's text on subsequent frames, keeping the original ts", () => {
      let state = translateReducer(initialTranslateState, {
        type: "captions",
        source: "hol",
        translation: "hel",
        speaker: "user-1",
        language: "es",
        ts: 1000,
      });
      state = translateReducer(state, {
        type: "captions",
        source: "hola mundo",
        translation: "hello world",
        speaker: "user-1",
        language: "es",
        ts: 2000, // a later frame's ts must NOT overwrite the creation ts
      });
      expect(state.utterances).toHaveLength(1);
      expect(state.utterances[0]).toMatchObject({
        source: "hola mundo",
        translation: "hello world",
        ts: 1000,
      });
    });

    it("starts a new utterance after the previous one was finalized", () => {
      let state = translateReducer(initialTranslateState, {
        type: "captions",
        source: "a",
        translation: "a",
        speaker: "user-1",
        language: "es",
        ts: 1000,
      });
      state = translateReducer(state, { type: "utterance-end", speaker: "user-1", language: "es" });
      state = translateReducer(state, {
        type: "captions",
        source: "b",
        translation: "b",
        speaker: "user-2",
        language: "en",
        ts: 2000,
      });
      expect(state.utterances).toHaveLength(2);
      expect(state.utterances[0]).toMatchObject({ source: "a", live: false });
      expect(state.utterances[1]).toMatchObject({ source: "b", live: true });
    });

    it("drops an empty caption frame when there's no live utterance to patch", () => {
      // e.g. a Soniox payload with no new tokens, arriving right after the
      // previous utterance closed - shouldn't spawn a speaker-less,
      // text-less card with just a timestamp.
      let state = translateReducer(initialTranslateState, {
        type: "captions",
        source: "a",
        translation: "a",
        speaker: "user-1",
        language: "es",
        ts: 1000,
      });
      state = translateReducer(state, { type: "utterance-end", speaker: "user-1", language: "es" });
      state = translateReducer(state, {
        type: "captions",
        source: "",
        translation: "",
        speaker: null,
        language: null,
        ts: 2000,
      });
      expect(state.utterances).toHaveLength(1);
      expect(state.utterances[0]).toMatchObject({ source: "a", live: false });
    });

    it("still patches an already-live utterance even if the new frame is empty", () => {
      let state = translateReducer(initialTranslateState, {
        type: "captions",
        source: "a",
        translation: "a",
        speaker: "user-1",
        language: "es",
        ts: 1000,
      });
      state = translateReducer(state, {
        type: "captions",
        source: "",
        translation: "",
        speaker: null,
        language: null,
        ts: 2000,
      });
      expect(state.utterances).toHaveLength(1);
      expect(state.utterances[0]).toMatchObject({
        source: "",
        translation: "",
        live: true,
        ts: 1000,
      });
    });
  });

  describe("audio-start", () => {
    it("stamps spokenLang onto the still-live utterance", () => {
      let state = translateReducer(initialTranslateState, {
        type: "captions",
        source: "a",
        translation: "b",
        speaker: null,
        language: "es",
        ts: 1000,
      });
      state = translateReducer(state, { type: "audio-start", language: "en" });
      expect(state.utterances[0].spokenLang).toBe("en");
    });

    it("is a no-op with no live utterance or no language", () => {
      const noUtterance = translateReducer(initialTranslateState, {
        type: "audio-start",
        language: "en",
      });
      expect(noUtterance).toBe(initialTranslateState);

      let withLive = translateReducer(initialTranslateState, {
        type: "captions",
        source: "a",
        translation: "b",
        speaker: null,
        language: "es",
        ts: 1000,
      });
      const beforeNullLang = withLive;
      withLive = translateReducer(withLive, { type: "audio-start", language: null });
      expect(withLive).toBe(beforeNullLang);
    });
  });

  describe("utterance-end", () => {
    it("marks the last utterance not-live and only overwrites language/speaker when provided", () => {
      let state = translateReducer(initialTranslateState, {
        type: "captions",
        source: "a",
        translation: "b",
        speaker: "user-1",
        language: "es",
        ts: 1000,
      });
      // The idle_watchdog fallback path: bare utterance_end, no fields.
      state = translateReducer(state, { type: "utterance-end" });
      expect(state.utterances[0]).toMatchObject({ live: false, speaker: "user-1", language: "es" });
    });

    it("overwrites language/speaker when the server does provide them", () => {
      let state = translateReducer(initialTranslateState, {
        type: "captions",
        source: "a",
        translation: "b",
        speaker: "user-1",
        language: "es",
        ts: 1000,
      });
      state = translateReducer(state, { type: "utterance-end", speaker: "user-2", language: "en" });
      expect(state.utterances[0]).toMatchObject({ live: false, speaker: "user-2", language: "en" });
    });

    it("is a no-op with no utterances at all", () => {
      const state = translateReducer(initialTranslateState, { type: "utterance-end" });
      expect(state).toBe(initialTranslateState);
    });
  });

  it("server-error stops with the exact original message format", () => {
    const state = translateReducer(
      { ...initialTranslateState, status: "listening" },
      { type: "server-error", message: "oops" },
    );
    expect(state.status).toBe("stopped");
    expect(state.statusMessage).toBe("error: oops");
    expect(state.isError).toBe(true);
  });

  it("timeout stops with the server's message or the default", () => {
    const withMessage = translateReducer(
      { ...initialTranslateState, status: "listening" },
      { type: "timeout", message: "custom" },
    );
    expect(withMessage.statusMessage).toBe("custom");
    expect(withMessage.isError).toBe(false);

    const withoutMessage = translateReducer(
      { ...initialTranslateState, status: "listening" },
      { type: "timeout" },
    );
    expect(withoutMessage.statusMessage).toBe("Session ended after inactivity.");
  });

  it("ws-close recovers to stopped from any active status, and is a no-op when already idle/stopped", () => {
    const fromConnecting = translateReducer(
      { ...initialTranslateState, status: "connecting" },
      { type: "ws-close" },
    );
    expect(fromConnecting.status).toBe("stopped");
    expect(fromConnecting.isError).toBe(false);

    const noop = translateReducer(initialTranslateState, { type: "ws-close" });
    expect(noop).toBe(initialTranslateState);
  });

  it("ws-error stops with 'connection failed'", () => {
    const state = translateReducer(
      { ...initialTranslateState, status: "listening" },
      { type: "ws-error" },
    );
    expect(state.status).toBe("stopped");
    expect(state.statusMessage).toBe("connection failed");
    expect(state.isError).toBe(true);
  });

  it("manual-stop stops an active session and is a no-op when idle", () => {
    const stopped = translateReducer(
      { ...initialTranslateState, status: "listening" },
      { type: "manual-stop" },
    );
    expect(stopped.status).toBe("stopped");
    expect(stopped.statusMessage).toBe("stopped");

    const noop = translateReducer(initialTranslateState, { type: "manual-stop" });
    expect(noop).toBe(initialTranslateState);
  });

  it("restart-started and restart-cleared set the transient status text", () => {
    const restarting = translateReducer(initialTranslateState, { type: "restart-started" });
    expect(restarting.statusMessage).toBe("restarting");

    const cleared = translateReducer(initialTranslateState, { type: "restart-cleared" });
    expect(cleared.statusMessage).toBe("cleared");
  });

  it("reconnect-scheduled sets reconnecting + a status message but leaves status untouched, only while active", () => {
    const state = translateReducer(
      { ...initialTranslateState, status: "listening" },
      { type: "reconnect-scheduled", attempt: 2 },
    );
    expect(state.status).toBe("listening");
    expect(state.reconnecting).toBe(true);
    expect(state.statusMessage).toContain("attempt 2");

    const stoppedInput: TranslateState = { ...initialTranslateState, status: "stopped" };
    const noop = translateReducer(stoppedInput, { type: "reconnect-scheduled", attempt: 1 });
    expect(noop).toBe(stoppedInput);
  });

  it("reconnected returns to listening and clears reconnecting", () => {
    const state = translateReducer(
      { ...initialTranslateState, status: "listening", reconnecting: true },
      { type: "reconnected" },
    );
    expect(state.status).toBe("listening");
    expect(state.statusMessage).toBe("listening");
    expect(state.reconnecting).toBe(false);
  });

  it("giving up (ws-close) after reconnect attempts also clears reconnecting", () => {
    const state = translateReducer(
      { ...initialTranslateState, status: "listening", reconnecting: true },
      { type: "ws-close" },
    );
    expect(state.status).toBe("stopped");
    expect(state.reconnecting).toBe(false);
  });

  it("tab-hidden sets backgrounded only while listening", () => {
    const whileListening = translateReducer(
      { ...initialTranslateState, status: "listening" },
      { type: "tab-hidden" },
    );
    expect(whileListening.backgrounded).toBe(true);

    const stoppedInput: TranslateState = { ...initialTranslateState, status: "stopped" };
    const whileStopped = translateReducer(stoppedInput, { type: "tab-hidden" });
    expect(whileStopped.backgrounded).toBe(false);
    expect(whileStopped).toBe(stoppedInput); // true no-op, same reference
  });

  it("tab-visible clears backgrounded regardless of status", () => {
    const state = translateReducer(
      { ...initialTranslateState, status: "listening", backgrounded: true },
      { type: "tab-visible" },
    );
    expect(state.backgrounded).toBe(false);
  });

  it("tab-hidden/tab-visible are no-ops (same reference) when nothing changes", () => {
    const idle = initialTranslateState;
    expect(translateReducer(idle, { type: "tab-hidden" })).toBe(idle);
    expect(translateReducer(idle, { type: "tab-visible" })).toBe(idle);
  });

  it("clear empties utterances independent of status", () => {
    const withData: TranslateState = {
      ...initialTranslateState,
      status: "stopped",
      utterances: [
        {
          speaker: "user-1",
          language: "es",
          spokenLang: null,
          source: "a",
          translation: "b",
          live: false,
          ts: 1,
        },
      ],
    };
    const cleared = translateReducer(withData, { type: "clear" });
    expect(cleared.utterances).toEqual([]);
    expect(cleared.status).toBe("stopped");
  });
});
