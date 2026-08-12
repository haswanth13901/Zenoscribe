import { describe, expect, it } from "vitest";
import { initialRecorderState, recorderReducer } from "@/features/recorder/model/recorderReducer";
import type { RecorderState } from "@/features/recorder/model/types";

describe("recorderReducer", () => {
  it("starts idle", () => {
    expect(initialRecorderState.status).toBe("idle");
  });

  it("walks the happy path: connecting -> authenticating -> listening", () => {
    let state = initialRecorderState;
    state = recorderReducer(state, { type: "start-requested" });
    expect(state.status).toBe("connecting");
    expect(state.isError).toBe(false);

    state = recorderReducer(state, { type: "ws-open" });
    expect(state.status).toBe("authenticating");

    state = recorderReducer(state, { type: "ws-ready" });
    expect(state.status).toBe("authenticating"); // no visible transition yet

    state = recorderReducer(state, { type: "audio-ready" });
    expect(state.status).toBe("listening");
    expect(state.statusMessage).toBe("listening");
    expect(state.isError).toBe(false);
  });

  it("ignores a second start-requested while already connecting/listening", () => {
    let state = recorderReducer(initialRecorderState, { type: "start-requested" });
    const afterFirst = state;
    state = recorderReducer(state, { type: "start-requested" });
    expect(state).toBe(afterFirst); // unchanged reference, true no-op
  });

  it("mic-denied goes to stopped with the exact original message format", () => {
    const state = recorderReducer(initialRecorderState, {
      type: "mic-denied",
      message: "Permission denied",
    });
    expect(state.status).toBe("stopped");
    expect(state.statusMessage).toBe("mic error: Permission denied");
    expect(state.isError).toBe(true);
  });

  it("partial replaces, not appends", () => {
    let state = initialRecorderState;
    state = recorderReducer(state, { type: "partial", speaker: "user-1", text: "hello" });
    state = recorderReducer(state, { type: "partial", speaker: "user-1", text: "hello world" });
    expect(state.partial).toEqual({ speaker: "user-1", text: "hello world" });
  });

  it("final appends a turn and clears any pending partial", () => {
    let state = initialRecorderState;
    state = recorderReducer(state, { type: "partial", speaker: "user-1", text: "hel" });
    state = recorderReducer(state, { type: "final", speaker: "user-1", text: "hello", start: 1.2 });
    expect(state.turns).toEqual([{ speaker: "user-1", text: "hello", start: 1.2 }]);
    expect(state.partial).toBeNull();
  });

  it("accumulates multiple final turns in order", () => {
    let state = initialRecorderState;
    state = recorderReducer(state, { type: "final", speaker: "user-1", text: "one", start: 0 });
    state = recorderReducer(state, { type: "final", speaker: "user-2", text: "two", start: 1 });
    expect(state.turns.map((t) => t.text)).toEqual(["one", "two"]);
  });

  it("audio-fail stops with the exact original message format and clears partial", () => {
    let state = recorderReducer(initialRecorderState, {
      type: "partial",
      speaker: "user-1",
      text: "x",
    });
    state = recorderReducer(state, { type: "audio-fail", message: "NotAllowedError" });
    expect(state.status).toBe("stopped");
    expect(state.statusMessage).toBe("audio setup failed: NotAllowedError");
    expect(state.isError).toBe(true);
    expect(state.partial).toBeNull();
  });

  it("server-error stops from listening with the exact original message format", () => {
    let state: RecorderState = {
      ...initialRecorderState,
      status: "listening",
      statusMessage: "listening",
    };
    state = recorderReducer(state, { type: "server-error", message: "boom" });
    expect(state.status).toBe("stopped");
    expect(state.statusMessage).toBe("error: boom");
    expect(state.isError).toBe(true);
  });

  it("ws-error stops with 'connection failed', regardless of prior status", () => {
    const state = recorderReducer(
      { ...initialRecorderState, status: "listening" },
      { type: "ws-error" },
    );
    expect(state.status).toBe("stopped");
    expect(state.statusMessage).toBe("connection failed");
    expect(state.isError).toBe(true);
  });

  it("ws-close recovers to stopped from any active status (fixes the original's stuck-toggle gap while connecting)", () => {
    const fromConnecting = recorderReducer(
      { ...initialRecorderState, status: "connecting" },
      { type: "ws-close" },
    );
    expect(fromConnecting.status).toBe("stopped");
    expect(fromConnecting.isError).toBe(false);

    const fromListening = recorderReducer(
      { ...initialRecorderState, status: "listening" },
      { type: "ws-close" },
    );
    expect(fromListening.status).toBe("stopped");
  });

  it("ws-close while already idle/stopped is a no-op", () => {
    const state = recorderReducer(initialRecorderState, { type: "ws-close" });
    expect(state).toBe(initialRecorderState);
  });

  it("manual-stop stops an active session and is a no-op when idle", () => {
    const stopped = recorderReducer(
      { ...initialRecorderState, status: "listening" },
      { type: "manual-stop" },
    );
    expect(stopped.status).toBe("stopped");
    expect(stopped.statusMessage).toBe("stopped");
    expect(stopped.isError).toBe(false);

    const noop = recorderReducer(initialRecorderState, { type: "manual-stop" });
    expect(noop).toBe(initialRecorderState);
  });

  it("clear empties turns/partial independent of status", () => {
    const withData: RecorderState = {
      ...initialRecorderState,
      status: "stopped",
      turns: [{ speaker: "user-1", text: "hi", start: 0 }],
      partial: { speaker: "user-1", text: "..." },
    };
    const cleared = recorderReducer(withData, { type: "clear" });
    expect(cleared.turns).toEqual([]);
    expect(cleared.partial).toBeNull();
    expect(cleared.status).toBe("stopped"); // status untouched
  });
});
