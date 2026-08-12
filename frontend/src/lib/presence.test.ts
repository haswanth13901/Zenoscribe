import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { presence } from "./presence";

describe("presence", () => {
  const now = new Date(2026, 5, 15, 12, 0, 0);

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(now);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns never for a null last_seen", () => {
    expect(presence(null)).toEqual({ online: false, label: "never" });
  });

  it("returns online within the 5-minute threshold", () => {
    const threeMinAgo = new Date(now.getTime() - 3 * 60 * 1000).toISOString();
    expect(presence(threeMinAgo)).toEqual({ online: true, label: "online" });
  });

  it("returns Xm ago between 5 minutes and an hour", () => {
    const tenMinAgo = new Date(now.getTime() - 10 * 60 * 1000).toISOString();
    expect(presence(tenMinAgo)).toEqual({ online: false, label: "10m ago" });
  });

  it("returns Xh ago between an hour and a day", () => {
    const threeHoursAgo = new Date(now.getTime() - 3 * 60 * 60 * 1000).toISOString();
    expect(presence(threeHoursAgo)).toEqual({ online: false, label: "3h ago" });
  });

  it("returns Xd ago beyond a day", () => {
    const twoDaysAgo = new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000).toISOString();
    expect(presence(twoDaysAgo)).toEqual({ online: false, label: "2d ago" });
  });
});
