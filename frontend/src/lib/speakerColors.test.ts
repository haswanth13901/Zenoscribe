import { describe, expect, it } from "vitest";
import { assignSpeakerColors } from "./speakerColors";

function u(speaker: string | null) {
  return { speaker };
}

describe("assignSpeakerColors", () => {
  it("assigns colors in first-appearance order, starting at 1", () => {
    const colors = assignSpeakerColors([u("user-2"), u("user-1"), u("user-2")]);
    expect(colors.get("user-2")).toBe(1);
    expect(colors.get("user-1")).toBe(2);
  });

  it("gives the same speaker a stable color across multiple appearances", () => {
    const colors = assignSpeakerColors([u("user-1"), u("user-2"), u("user-1"), u("user-1")]);
    expect(colors.get("user-1")).toBe(1);
    expect(colors.get("user-2")).toBe(2);
  });

  it("ignores null speakers", () => {
    const colors = assignSpeakerColors([u(null), u("user-1"), u(null)]);
    expect(colors.size).toBe(1);
    expect(colors.get("user-1")).toBe(1);
  });

  it("wraps around after 4 distinct speakers", () => {
    const colors = assignSpeakerColors([u("a"), u("b"), u("c"), u("d"), u("e")]);
    expect(colors.get("a")).toBe(1);
    expect(colors.get("b")).toBe(2);
    expect(colors.get("c")).toBe(3);
    expect(colors.get("d")).toBe(4);
    expect(colors.get("e")).toBe(1);
  });

  it("returns an empty map for no utterances", () => {
    expect(assignSpeakerColors([]).size).toBe(0);
  });
});
