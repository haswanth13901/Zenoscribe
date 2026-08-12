import { describe, expect, it } from "vitest";
import { formatTodayLabel, getGreeting } from "./greeting";

describe("getGreeting", () => {
  it("says morning just before noon", () => {
    expect(getGreeting(new Date(2026, 0, 1, 11, 59), "Ada")).toBe("Good morning, Ada");
  });

  it("says afternoon starting at noon", () => {
    expect(getGreeting(new Date(2026, 0, 1, 12, 0), "Ada")).toBe("Good afternoon, Ada");
  });

  it("says afternoon just before 6pm", () => {
    expect(getGreeting(new Date(2026, 0, 1, 17, 59), "Ada")).toBe("Good afternoon, Ada");
  });

  it("says evening starting at 6pm", () => {
    expect(getGreeting(new Date(2026, 0, 1, 18, 0), "Ada")).toBe("Good evening, Ada");
  });
});

describe("formatTodayLabel", () => {
  it("formats as 'Weekday, D Month'", () => {
    // 2026-01-01 is a Thursday.
    expect(formatTodayLabel(new Date(2026, 0, 1))).toBe("Thursday, 1 January");
  });
});
