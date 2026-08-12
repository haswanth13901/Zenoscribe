import type { ReactElement } from "react";
import type { Recording } from "@/entities/recording/model/types";
import { computeMonthlyStats } from "@/shared/lib/stats";
import styles from "./HomePage.module.css";

interface MonthlyStatsProps {
  recordings: Recording[] | undefined;
  isError: boolean;
  now: Date;
}

// Only rendered for a successful, non-error fetch - on error it shows a
// neutral placeholder instead of stale/blank numbers (the second concrete
// fix for the original page's silent-on-failure #stats block).
export function MonthlyStats({ recordings, isError, now }: MonthlyStatsProps): ReactElement {
  if (isError || !recordings) {
    return (
      <div className={styles.stats}>
        <div className={styles.stat}>
          <div className={styles.num}>—</div>
          <div className={styles.label}>transcribed this month</div>
        </div>
        <div className={styles.stat}>
          <div className={styles.num}>—</div>
          <div className={styles.label}>sessions saved</div>
        </div>
      </div>
    );
  }

  const { hours, minutes, sessionCount } = computeMonthlyStats(recordings, now);

  return (
    <div className={styles.stats}>
      <div className={styles.stat}>
        <div className={styles.num}>
          {hours}h {minutes}m
        </div>
        <div className={styles.label}>transcribed this month</div>
      </div>
      <div className={styles.stat}>
        <div className={styles.num}>{sessionCount}</div>
        <div className={styles.label}>sessions saved</div>
      </div>
    </div>
  );
}
