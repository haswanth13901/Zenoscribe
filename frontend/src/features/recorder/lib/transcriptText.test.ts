import { describe, expect, it } from "vitest";
import { turnsToText } from "@/features/recorder/lib/transcriptText";

describe("turnsToText", () => {
  it("formats a single turn as [Ns] speaker: text", () => {
    expect(turnsToText([{ speaker: "user-1", text: "hello", start: 1.25 }])).toBe(
      "[1.3s] user-1: hello",
    );
  });

  it("treats a null start as 0.0s", () => {
    expect(turnsToText([{ speaker: "user-1", text: "hi", start: null }])).toBe("[0.0s] user-1: hi");
  });

  it("joins multiple turns with newlines, in order", () => {
    const text = turnsToText([
      { speaker: "user-1", text: "one", start: 0 },
      { speaker: "user-2", text: "two", start: 2 },
    ]);
    expect(text).toBe("[0.0s] user-1: one\n[2.0s] user-2: two");
  });

  it("returns an empty string for no turns", () => {
    expect(turnsToText([])).toBe("");
  });
});
