import type { ReactElement } from "react";
import { useNavigate } from "react-router-dom";
import styles from "./ActionCards.module.css";

// Both /app and /translate are real in-SPA routes now, so both buttons
// navigate client-side.
export function ActionCards(): ReactElement {
  const navigate = useNavigate();

  return (
    <div className={styles.cards}>
      <div className={`${styles.card} ${styles.primary}`}>
        <h2>Start recording</h2>
        <p>Live transcription with speakers separated as they talk.</p>
        <button type="button" data-testid="go-record" onClick={() => navigate("/app")}>
          Start
        </button>
      </div>
      <div className={`${styles.card} ${styles.secondary}`}>
        <h2>Live translate</h2>
        <p>Two-way, spoken back in the other language.</p>
        <button type="button" data-testid="go-translate" onClick={() => navigate("/translate")}>
          Open
        </button>
      </div>
    </div>
  );
}
