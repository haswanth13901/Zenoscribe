// Ported 1:1 from home.html's inline greeting()/#today logic. Takes `date`
// as a parameter (instead of calling `new Date()` internally) so tests can
// pin a fixed reference date, especially across the morning/afternoon/
// evening hour boundaries.

export function getGreeting(date: Date, name: string): string {
  const h = date.getHours();
  const part = h < 12 ? "morning" : h < 18 ? "afternoon" : "evening";
  return `Good ${part}, ${name}`;
}

export function formatTodayLabel(date: Date): string {
  const weekday = date.toLocaleDateString("en-US", { weekday: "long" });
  const day = date.getDate();
  const month = date.toLocaleDateString("en-US", { month: "long" });
  return `${weekday}, ${day} ${month}`;
}
