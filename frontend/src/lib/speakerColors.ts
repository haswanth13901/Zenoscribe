// Ported from translate-views.js's stable-per-speaker-color-by-first-
// appearance logic (a 4-color palette, matching the --u1..--u4 tokens
// already used elsewhere for per-speaker coloring). Recomputed fresh from
// the current utterances array each call rather than kept as hidden
// module-level state like the original - since utterances only ever grow
// or get wiped entirely (never reordered/partially removed), this gives
// the same stable assignment in the common case. One acknowledged, minor
// divergence: after Restart clears the transcript, a speaker who spoke
// second in the previous session and speaks alone in the next one gets
// re-assigned the first color rather than keeping their earlier one - not
// worth carrying hidden cross-session state to preserve.
const PALETTE_SIZE = 4;

export function assignSpeakerColors(utterances: { speaker: string | null }[]): Map<string, number> {
  const colors = new Map<string, number>();
  let next = 0;
  for (const u of utterances) {
    if (u.speaker && !colors.has(u.speaker)) {
      colors.set(u.speaker, (next % PALETTE_SIZE) + 1); // 1..4, matching --u1..--u4
      next += 1;
    }
  }
  return colors;
}
