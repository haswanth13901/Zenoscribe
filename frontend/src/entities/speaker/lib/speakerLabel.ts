import { getInitials } from "@/shared/lib/initials";

export interface SpeakerLabel {
  name: string;
  initials: string;
}

const NUMBERED_SPEAKER = /^user[-_ ]?(\d+)$/i;

// Ported from recorder-turns.js's label(): "user-1" -> "Speaker 1"/"S1";
// anything else falls back to the same split-on-[\s._-]+ initials
// algorithm as getInitials, using the speaker string itself as the name.
export function getSpeakerLabel(speaker: string): SpeakerLabel {
  const m = NUMBERED_SPEAKER.exec(speaker || "");
  if (m) {
    return { name: `Speaker ${m[1]}`, initials: `S${m[1]}` };
  }
  const name = speaker || "Speaker";
  return { name, initials: getInitials(name) };
}
