import { describe, expect, it } from "vitest";
import { fmtDate } from "@/shared/lib/fmtDate";

describe("fmtDate", () => {
  it("returns an em dash for null/undefined", () => {
    expect(fmtDate(null)).toBe("—");
    expect(fmtDate(undefined)).toBe("—");
  });

  it("returns an em dash for an invalid date string", () => {
    expect(fmtDate("not-a-date")).toBe("—");
  });

  it("returns the locale string for a valid ISO date", () => {
    const iso = new Date(2026, 0, 15, 9, 30).toISOString();
    expect(fmtDate(iso)).toBe(new Date(iso).toLocaleString());
  });
});
