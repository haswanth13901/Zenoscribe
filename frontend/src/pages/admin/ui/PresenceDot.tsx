import type { ReactElement } from "react";
import type { Presence } from "@/shared/lib/presence";
import styles from "./PresenceDot.module.css";

interface PresenceDotProps {
  presence: Presence;
}

export function PresenceDot({ presence }: PresenceDotProps): ReactElement {
  return (
    <>
      <span className={`${styles.dot} ${presence.online ? styles.on : styles.off}`} />
      {presence.online ? presence.label : <span className={styles.label}>{presence.label}</span>}
    </>
  );
}
