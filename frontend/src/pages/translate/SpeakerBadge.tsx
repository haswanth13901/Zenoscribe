import type { ReactElement } from "react";
import { getSpeakerLabel } from "../../lib/speakerLabel";
import styles from "./SpeakerBadge.module.css";

interface SpeakerBadgeProps {
  speaker: string | null;
  /** 1..4, matching the --u1..--u4 tokens; undefined falls back to a muted color. */
  colorIndex?: number;
}

// Used by the stacked/focus views only - the columns view shows the raw
// speaker string instead (matches the original's own distinction: its
// native .cols DOM just shows `<span class="spk">{speaker}</span>`, while
// translate-views.js's stacked/focus cards apply this initials+name
// treatment via displayName()/initials(), which duplicated
// lib/speakerLabel.ts's logic - reused here instead).
export function SpeakerBadge({ speaker, colorIndex }: SpeakerBadgeProps): ReactElement | null {
  if (!speaker) return null;
  const label = getSpeakerLabel(speaker);
  return (
    <span className={styles.badge}>
      <span className={styles.avatar} data-color={colorIndex}>
        {label.initials}
      </span>
      <span className={styles.name}>{label.name}</span>
    </span>
  );
}
