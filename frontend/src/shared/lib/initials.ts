// Ported 1:1 from header.js's avatar-initials algorithm: split on
// whitespace/._- , use the first letter of the first two parts if there
// are at least two, otherwise the first two characters of the whole name.
export function getInitials(name: string): string {
  const parts = String(name)
    .split(/[\s._-]+/)
    .filter(Boolean);
  const raw = parts.length > 1 ? parts[0][0] + parts[1][0] : String(name).slice(0, 2);
  return raw.toUpperCase() || "··";
}
