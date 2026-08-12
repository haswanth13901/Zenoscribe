const ONLINE_MINUTES = 5;

function sinceText(iso: string): string {
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return "just now";
  const m = Math.floor(secs / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

export interface Presence {
  online: boolean;
  /** "never" | "just now" | "Xm ago" | "Xh ago" | "Xd ago" | "online" */
  label: string;
}

// Ported from admin.html's sinceText()/presence(). A null last_seen still
// renders a (muted) dot in the original, not "no dot" - {online:false,
// label:"never"} preserves that.
export function presence(lastSeen: string | null): Presence {
  if (!lastSeen) return { online: false, label: "never" };
  const mins = (Date.now() - new Date(lastSeen).getTime()) / 60000;
  if (mins < ONLINE_MINUTES) return { online: true, label: "online" };
  return { online: false, label: sinceText(lastSeen) };
}
