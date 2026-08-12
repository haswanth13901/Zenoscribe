import type { ReactElement } from "react";
import type { Recording } from "../../features/recordings/types";
import { fmtDur, fmtWhen } from "../../lib/formatters";
import styles from "./RecentSessions.module.css";

interface RecentSessionsProps {
  recordings: Recording[] | undefined;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  now: Date;
}

const MAX_ROWS = 4;

// Loading / error / empty / success, in that precedence - the concrete fix
// for the original page's bug where a fetch error and the legitimate
// "no recordings yet" empty state rendered as visually identical text with
// no way to retry.
export function RecentSessions({ recordings, isLoading, isError, onRetry, now }: RecentSessionsProps): ReactElement {
  if (isLoading) {
    return (
      <div className={styles.sessions}>
        <div className={styles.empty}>Loading...</div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className={styles.sessions}>
        <div className={styles.errorState}>
          Couldn't load your recordings.
          <button type="button" className={styles.retryBtn} onClick={onRetry}>
            Try again
          </button>
        </div>
      </div>
    );
  }

  if (!recordings || recordings.length === 0) {
    return (
      <div className={styles.sessions}>
        <div className={styles.empty}>No recordings yet. Press Start to make your first one.</div>
      </div>
    );
  }

  return (
    <div className={styles.sessions}>
      {recordings.slice(0, MAX_ROWS).map((r) => (
        <div className={styles.srow} key={r.id}>
          <div className={styles.title}>{r.preview || "(no speech detected)"}</div>
          <div className={styles.col}>{fmtWhen(r.started_at, now)}</div>
          <div className={styles.col}>{fmtDur(r.duration)}</div>
          <div className={styles.col}>{r.turn_count} turns</div>
        </div>
      ))}
    </div>
  );
}
