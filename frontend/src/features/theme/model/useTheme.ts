import { useCallback, useState } from "react";

const KEY = "zeno-theme";

export type Theme = "light" | "dark";

function readTheme(): Theme {
  // theme-preboot.js already set data-theme on <html> before paint; read
  // that instead of re-deriving from localStorage/matchMedia so this hook
  // can never disagree with what's already on screen.
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

/** Reads/writes the same localStorage key theme-preboot.js uses on every
 * page (including login.html), so the choice made here carries over there
 * too. */
export function useTheme(): { theme: Theme; toggleTheme: () => void } {
  const [theme, setTheme] = useState<Theme>(readTheme);

  const toggleTheme = useCallback(() => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // Ignore - worst case the choice doesn't persist across reloads.
    }
    setTheme(next);
  }, [theme]);

  return { theme, toggleTheme };
}
