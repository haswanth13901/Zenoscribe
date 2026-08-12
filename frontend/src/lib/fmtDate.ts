// Ported from admin.html's fmtDate - a plain locale datetime string.
// Deliberately distinct from formatters.ts's fmtWhen (home.html's fancier
// "Today HH:MM"/weekday-relative format for a different call site).
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "—" : d.toLocaleString();
}
