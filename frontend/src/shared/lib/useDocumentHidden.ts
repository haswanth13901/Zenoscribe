import { useEffect, useState } from "react";

function readHidden(): boolean {
  return typeof document !== "undefined" && document.hidden === true;
}

/** Tracks whether the tab is currently backgrounded or the screen is locked
 * (document.hidden via the visibilitychange event). Used by live-recording
 * pages to warn that mobile browsers may suspend JS/audio while
 * backgrounded, since a dropped WS session there would otherwise look like
 * a silent hang. Guarded the same way AppLayout guards matchMedia - jsdom
 * (the test env) does implement document.hidden/visibilitychange, but this
 * degrades to "never hidden" instead of throwing on any environment that
 * doesn't. */
export function useDocumentHidden(): boolean {
  const [hidden, setHidden] = useState(readHidden);

  useEffect(() => {
    if (typeof document === "undefined" || typeof document.addEventListener !== "function") {
      return;
    }
    const handleChange = () => setHidden(readHidden());
    document.addEventListener("visibilitychange", handleChange);
    return () => document.removeEventListener("visibilitychange", handleChange);
  }, []);

  return hidden;
}
