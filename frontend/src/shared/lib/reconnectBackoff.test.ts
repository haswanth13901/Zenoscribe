import { describe, expect, it } from "vitest";
import { reconnectDelayMs } from "@/shared/lib/reconnectBackoff";

describe("reconnectDelayMs", () => {
  it("doubles each attempt starting at 1s", () => {
    expect(reconnectDelayMs(1)).toBe(1000);
    expect(reconnectDelayMs(2)).toBe(2000);
    expect(reconnectDelayMs(3)).toBe(4000);
    expect(reconnectDelayMs(4)).toBe(8000);
  });

  it("caps at 16s for later attempts", () => {
    expect(reconnectDelayMs(5)).toBe(16000);
    expect(reconnectDelayMs(9)).toBe(16000);
  });
});
