import { describe, expect, it } from "vitest";
import type { Recording } from "../features/recordings/types";
import { computeMonthlyStats } from "./stats";

function rec(overrides: Partial<Recording>): Recording {
  return {
    id: "r1",
    username: "ada",
    user_id: "u1",
    started_at: new Date(2026, 5, 1).toISOString(),
    duration: 0,
    turn_count: 0,
    preview: "",
    ...overrides,
  };
}

describe("computeMonthlyStats", () => {
  const now = new Date(2026, 5, 15); // June 2026

  it("returns zeros for an empty list", () => {
    expect(computeMonthlyStats([], now)).toEqual({ hours: 0, minutes: 0, sessionCount: 0 });
  });

  it("sums only this-month durations into hours/minutes", () => {
    const recordings = [
      rec({ started_at: new Date(2026, 5, 2).toISOString(), duration: 3600 }), // in June
      rec({ started_at: new Date(2026, 5, 10).toISOString(), duration: 1800 }), // in June
      rec({ started_at: new Date(2026, 4, 20).toISOString(), duration: 9999 }), // in May, excluded from time sum
    ];
    const result = computeMonthlyStats(recordings, now);
    expect(result.hours).toBe(1);
    expect(result.minutes).toBe(30);
  });

  it("counts sessionCount across ALL recordings, not just this month (matches ported behavior)", () => {
    const recordings = [
      rec({ started_at: new Date(2026, 5, 2).toISOString() }),
      rec({ started_at: new Date(2026, 4, 20).toISOString() }),
      rec({ started_at: new Date(2025, 0, 1).toISOString() }),
    ];
    expect(computeMonthlyStats(recordings, now).sessionCount).toBe(3);
  });
});
