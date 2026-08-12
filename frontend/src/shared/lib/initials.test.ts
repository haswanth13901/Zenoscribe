import { describe, expect, it } from "vitest";
import { getInitials } from "@/shared/lib/initials";

describe("getInitials", () => {
  it("uses first letter of first two words", () => {
    expect(getInitials("Ada Lovelace")).toBe("AL");
  });

  it("splits on dots/underscores/hyphens too", () => {
    expect(getInitials("ada.lovelace")).toBe("AL");
    expect(getInitials("ada_lovelace")).toBe("AL");
    expect(getInitials("ada-lovelace")).toBe("AL");
  });

  it("falls back to first two characters for a single word", () => {
    expect(getInitials("ada")).toBe("AD");
  });

  it("falls back to a placeholder for an empty name", () => {
    expect(getInitials("")).toBe("··");
  });
});
