// Ported 1:1 from home.html's inline fmtDur/fmtWhen.

export function fmtDur(seconds: number | null | undefined): string {
  const s = Math.round(seconds || 0);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// Ported 1:1 from translate.html's fmtElapsed - zero-padded mm:ss, unlike
// fmtDur which doesn't pad minutes.
export function fmtElapsed(ms: number): string {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

// Short local time (e.g. "14:05"), used for the stacked/focus transcript
// views' per-utterance meta line.
export function fmtTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function fmtWhen(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";

  const sameDay = d.toDateString() === now.toDateString();
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  if (sameDay) return `Today ${time}`;

  const nowMidnight = new Date(now).setHours(0, 0, 0, 0);
  const dMidnight = new Date(d).setHours(0, 0, 0, 0);
  const diffDays = Math.round((nowMidnight - dMidnight) / 86400000);
  if (diffDays >= 0 && diffDays < 6) {
    return `${d.toLocaleDateString([], { weekday: "short" })} ${time}`;
  }
  return `${d.toLocaleDateString([], { day: "2-digit", month: "short" })} ${time}`;
}
