import type { Turn } from "@/features/recorder/model/types";

export function turnsToText(turns: Turn[]): string {
  return turns.map((t) => `[${(t.start ?? 0).toFixed(1)}s] ${t.speaker}: ${t.text}`).join("\n");
}
