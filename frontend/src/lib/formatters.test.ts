import { describe, expect, it } from "vitest";
import { fmtDur, fmtElapsed, fmtTime, fmtWhen } from "./formatters";

describe("fmtDur", () => {
  it("formats zero seconds", () => {
    expect(fmtDur(0)).toBe("0:00");
  });

  it("pads seconds under 10", () => {
    expect(fmtDur(65)).toBe("1:05");
  });

  it("floors minutes and rounds seconds", () => {
    expect(fmtDur(125.6)).toBe("2:06");
  });

  it("treats null/undefined as zero", () => {
    expect(fmtDur(undefined)).toBe("0:00");
    expect(fmtDur(null)).toBe("0:00");
  });
});

// fmtWhen's own output is locale-dependent (it calls toLocaleDateString/
// toLocaleTimeString with no explicit locale, same as the original inline
// code it was ported from) - these tests compute the expected string with
// the same Intl calls rather than hardcoding a locale's exact output, so
// they hold regardless of which locale the test runner's environment uses.
function localeTime(d: Date): string {
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

describe("fmtWhen", () => {
  const now = new Date(2026, 5, 15, 14, 30); // some fixed reference date

  it("returns 'Today HH:MM' for a same-day timestamp", () => {
    const sameDay = new Date(2026, 5, 15, 9, 5);
    expect(fmtWhen(sameDay.toISOString(), now)).toBe(`Today ${localeTime(sameDay)}`);
  });

  it("returns weekday + time within the last 6 days", () => {
    const threeDaysAgo = new Date(2026, 5, 12, 9, 5);
    const expected = `${threeDaysAgo.toLocaleDateString([], { weekday: "short" })} ${localeTime(threeDaysAgo)}`;
    expect(fmtWhen(threeDaysAgo.toISOString(), now)).toBe(expected);
  });

  it("returns day+month for dates 6+ days ago", () => {
    const eightDaysAgo = new Date(2026, 5, 7, 9, 5);
    const expected = `${eightDaysAgo.toLocaleDateString([], { day: "2-digit", month: "short" })} ${localeTime(eightDaysAgo)}`;
    expect(fmtWhen(eightDaysAgo.toISOString(), now)).toBe(expected);
  });

  it("returns an em dash for an invalid date", () => {
    expect(fmtWhen("not-a-date", now)).toBe("—");
  });
});

describe("fmtElapsed", () => {
  it("zero-pads both minutes and seconds", () => {
    expect(fmtElapsed(5000)).toBe("00:05");
  });

  it("formats multi-digit minutes", () => {
    expect(fmtElapsed(65 * 1000)).toBe("01:05");
  });

  it("floors partial seconds", () => {
    expect(fmtElapsed(1999)).toBe("00:01");
  });
});

describe("fmtTime", () => {
  it("matches the locale time string for the given timestamp", () => {
    const d = new Date(2026, 0, 1, 14, 5);
    expect(fmtTime(d.getTime())).toBe(d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }));
  });
});
