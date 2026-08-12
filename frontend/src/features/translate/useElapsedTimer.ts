import { useEffect, useState } from "react";
import { fmtElapsed } from "../../lib/formatters";

// Ported from translate.html's startTimer()/updateTimer()/stopTimer() - a
// live "mm:ss" ticking display. Kept out of translateReducer since a
// ticking clock doesn't belong in dispatched state; this just re-renders
// locally once a second while `active`.
export function useElapsedTimer(active: boolean): string | null {
  const [elapsed, setElapsed] = useState<string | null>(null);

  useEffect(() => {
    if (!active) {
      setElapsed(null);
      return;
    }
    const start = Date.now();
    setElapsed(fmtElapsed(0));
    const id = setInterval(() => setElapsed(fmtElapsed(Date.now() - start)), 1000);
    return () => clearInterval(id);
  }, [active]);

  return elapsed;
}
