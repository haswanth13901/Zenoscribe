import { describe, expect, it } from "vitest";
import { getSpeakerLabel } from "@/entities/speaker/lib/speakerLabel";

describe("getSpeakerLabel", () => {
  it("maps user-N to Speaker N / SN", () => {
    expect(getSpeakerLabel("user-1")).toEqual({ name: "Speaker 1", initials: "S1" });
    expect(getSpeakerLabel("user_2")).toEqual({ name: "Speaker 2", initials: "S2" });
    expect(getSpeakerLabel("USER3")).toEqual({ name: "Speaker 3", initials: "S3" });
    expect(getSpeakerLabel("user 12")).toEqual({ name: "Speaker 12", initials: "S12" });
  });

  it("falls back to initials-from-name for non-numbered speakers", () => {
    expect(getSpeakerLabel("Ada Lovelace")).toEqual({ name: "Ada Lovelace", initials: "AL" });
  });

  it("falls back to 'Speaker'/'SP' for an empty speaker string", () => {
    expect(getSpeakerLabel("")).toEqual({ name: "Speaker", initials: "SP" });
  });
});
