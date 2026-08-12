import { useEffect, useRef, type ReactElement } from "react";
import { getSpeakerLabel } from "@/entities/speaker/lib/speakerLabel";
import type { PartialTurn, Turn } from "@/features/recorder/model/types";
import styles from "./TurnList.module.css";

interface TurnListProps {
  turns: Turn[];
  partial: PartialTurn | null;
}

function TurnRow({
  speaker,
  text,
  start,
  isPartial,
}: {
  speaker: string;
  text: string;
  start?: number | null;
  isPartial?: boolean;
}): ReactElement {
  const label = getSpeakerLabel(speaker);
  return (
    <div className={`${styles.turn} ${isPartial ? styles.partial : ""}`}>
      <div className={styles.who}>
        <span className={styles.avatar} data-speaker={speaker}>
          {label.initials}
        </span>
        <span>{label.name}</span>
      </div>
      <div className={styles.body}>
        {text}
        {start != null && <span className={styles.ts}>{start.toFixed(1)}s</span>}
      </div>
    </div>
  );
}

// Port of index.html's #transcript rendering (addTurn/showPartial) as
// native React state-driven rendering, replacing recorder-turns.js's
// monkey-patch-and-decorate approach entirely.
export function TurnList({ turns, partial }: TurnListProps): ReactElement {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current?.parentElement;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns.length, partial]);

  if (turns.length === 0 && !partial) {
    return (
      <div className={styles.wrap} ref={containerRef}>
        <div className={styles.empty}>Press Start and speak.</div>
      </div>
    );
  }

  return (
    <div className={styles.wrap} ref={containerRef}>
      {turns.map((t, i) => (
        <TurnRow key={i} speaker={t.speaker} text={t.text} start={t.start} />
      ))}
      {partial && <TurnRow speaker={partial.speaker} text={partial.text} isPartial />}
    </div>
  );
}
