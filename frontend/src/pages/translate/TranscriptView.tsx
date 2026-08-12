import { useMemo, type ReactElement } from "react";
import { assignSpeakerColors } from "../../lib/speakerColors";
import type { Utterance } from "../../features/translate/types";
import { UtteranceCard } from "./UtteranceCard";
import styles from "./TranscriptView.module.css";

export type ViewMode = "columns" | "stacked" | "focus";

interface TranscriptViewProps {
  utterances: Utterance[];
  view: ViewMode;
  langName: (code: string | null) => string;
}

function ColumnsPanel({
  title,
  colorClassName,
  utterances,
  text,
  emptyText,
}: {
  title: string;
  colorClassName: string;
  utterances: Utterance[];
  text: (u: Utterance) => string;
  emptyText: string;
}): ReactElement {
  return (
    <div className={`${styles.col} ${colorClassName}`}>
      <h2>{title}</h2>
      <div className={styles.stream}>
        {utterances.length === 0 ? (
          <div className={styles.empty}>{emptyText}</div>
        ) : (
          utterances.map((u, i) => (
            <div key={i} className={`${styles.utt} ${u.live ? styles.partial : ""}`}>
              {u.speaker && <span className={styles.spk}>{u.speaker}</span>}
              {text(u)}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// Real-state replacement for translate-views.js's MutationObserver-based
// re-pairing: since utterances are now an ordered array (not derived from
// the DOM), all three views render straight from the same data - the
// columns view (the original page's own native DOM) reads .source/
// .translation directly per side; stacked/focus (translate-views.js's
// additions) pair them into one card via UtteranceCard.
export function TranscriptView({ utterances, view, langName }: TranscriptViewProps): ReactElement {
  const colors = useMemo(() => assignSpeakerColors(utterances), [utterances]);

  if (view === "columns") {
    return (
      <div className={styles.cols}>
        <ColumnsPanel
          title="Heard"
          colorClassName={styles.colSrc}
          utterances={utterances}
          text={(u) => u.source}
          emptyText="Source speech appears here."
        />
        <ColumnsPanel
          title="Translation"
          colorClassName={styles.colTgt}
          utterances={utterances}
          text={(u) => u.translation}
          emptyText="Translation appears here."
        />
      </div>
    );
  }

  const list = view === "focus" ? utterances.slice(-1) : utterances;
  return (
    <div className={styles.stack}>
      {list.length === 0 ? (
        <div className={styles.empty}>Nothing yet.</div>
      ) : (
        list.map((u, i) => (
          <UtteranceCard
            key={i}
            utterance={u}
            colorIndex={u.speaker ? colors.get(u.speaker) : undefined}
            langName={langName}
            large={view === "focus"}
          />
        ))
      )}
    </div>
  );
}
