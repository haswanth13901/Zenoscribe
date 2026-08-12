import type { ReactElement } from "react";
import { fmtTime } from "../../lib/formatters";
import type { Utterance } from "../../features/translate/types";
import { SpeakerBadge } from "./SpeakerBadge";
import styles from "./UtteranceCard.module.css";

interface UtteranceCardProps {
  utterance: Utterance;
  colorIndex?: number;
  langName: (code: string | null) => string;
  /** Focus view renders one card larger. */
  large?: boolean;
}

// Used by the stacked and focus views (translate-views.js's card
// rendering), showing both source and translation together with speaker/
// language/time meta - unlike the columns view's plain per-side text.
export function UtteranceCard({ utterance, colorIndex, langName, large }: UtteranceCardProps): ReactElement {
  return (
    <div className={`${styles.card} ${utterance.live ? styles.partial : ""} ${large ? styles.large : ""}`}>
      <div className={styles.head}>
        <SpeakerBadge speaker={utterance.speaker} colorIndex={colorIndex} />
        <span className={styles.meta}>
          {langName(utterance.language)} · {fmtTime(utterance.ts)}
        </span>
      </div>
      <div className={styles.source}>{utterance.source}</div>
      <div className={styles.translation}>
        {utterance.translation}
        {utterance.spokenLang && <span className={styles.spokenTag}>spoken in {langName(utterance.spokenLang)}</span>}
      </div>
    </div>
  );
}
