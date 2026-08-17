import type { ReactElement } from "react";
import { getSpeakerLabel } from "@/entities/speaker/lib/speakerLabel";
import type { TranscribeTurn } from "@/features/transcribe/api/transcribeApi";
import styles from "./TranscriptTurns.module.css";

interface TranscriptTurnsProps {
  turns: TranscribeTurn[];
  emptyText: string;
}

// Renders a batch-transcribe result as a speaker-by-speaker conversation
// (matching how RecorderPage's TurnList shows live turns) instead of
// flattening every turn's text into one undifferentiated paragraph.
export function TranscriptTurns({ turns, emptyText }: TranscriptTurnsProps): ReactElement {
  if (turns.length === 0) {
    return <div className={styles.empty}>{emptyText}</div>;
  }

  return (
    <div className={styles.wrap}>
      {turns.map((t, i) => {
        const label = getSpeakerLabel(t.speaker);
        return (
          <div key={i} className={styles.turn}>
            <div className={styles.who}>
              <span className={styles.avatar} data-speaker={t.speaker}>
                {label.initials}
              </span>
              <span>{label.name}</span>
            </div>
            <div className={styles.body}>
              <div className={styles.source}>{t.text}</div>
              {t.translation && <div className={styles.translation}>{t.translation}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
