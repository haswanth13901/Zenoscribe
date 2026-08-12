import type { Recording } from "@/entities/recording/model/types";

export interface MonthlyStats {
  hours: number;
  minutes: number;
  /** Total saved sessions (all-time, not month-filtered) - matches the
   * original "sessions saved" stat, which counts the full list. */
  sessionCount: number;
}

// Ported 1:1 from home.html's inline stats calculation in load().
export function computeMonthlyStats(recordings: Recording[], now: Date): MonthlyStats {
  const monthSeconds = recordings
    .filter((r) => {
      const d = new Date(r.started_at);
      return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth();
    })
    .reduce((sum, r) => sum + (r.duration || 0), 0);
  const minutes = Math.round(monthSeconds / 60);

  return {
    hours: Math.floor(minutes / 60),
    minutes: minutes % 60,
    sessionCount: recordings.length,
  };
}
