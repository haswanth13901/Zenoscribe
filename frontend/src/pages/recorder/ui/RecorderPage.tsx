import { useMemo, useState, type ReactElement } from "react";
import { useAppSelector } from "@/app/hooks";
import { AppLayout } from "@/widgets/app-layout/ui/AppLayout";
import { useRecorderConnection } from "@/features/recorder/model/useRecorderConnection";
import { triggerBlobDownload } from "@/shared/lib/download";
import { turnsToText } from "@/features/recorder/lib/transcriptText";
import { checkAudioCaptureSupport } from "@/shared/lib/browserSupport";
import { TurnList } from "@/pages/recorder/ui/TurnList";
import styles from "./RecorderPage.module.css";

// Rendered only inside <RequireAuth>, so `user` is guaranteed non-null here.
export function RecorderPage(): ReactElement {
  const user = useAppSelector((s) => s.auth.user)!;
  const { state, start, stop, clear } = useRecorderConnection();
  const [numSpeakers, setNumSpeakers] = useState("");
  // Checked once per mount rather than waiting for a Start click to hit a
  // cryptic native error - browser capabilities don't change mid-session.
  const support = useMemo(() => checkAudioCaptureSupport(), []);

  const isListening = state.status === "listening";
  const isBusy = state.status === "connecting" || state.status === "authenticating";
  const controlsLocked = isListening || isBusy;

  function handleToggle() {
    if (isListening) {
      stop();
    } else {
      const n = parseInt(numSpeakers, 10);
      start(Number.isFinite(n) && n > 0 ? n : undefined);
    }
  }

  function handleSave() {
    if (state.turns.length === 0) return;
    triggerBlobDownload(
      new Blob([turnsToText(state.turns)], { type: "text/plain" }),
      `transcript-${Date.now()}.txt`,
    );
  }

  return (
    <AppLayout user={user}>
      <div className={styles.toolbar}>
        <span
          data-testid="recorder-status"
          className={`${styles.status} ${isListening && !state.reconnecting ? styles.statusLive : ""} ${state.reconnecting ? styles.statusWarn : ""} ${state.isError ? styles.statusError : ""}`}
        >
          {state.statusMessage === "idle" ? "" : state.statusMessage}
        </span>
        <div className={styles.field} title="Optional hint for how many distinct voices to expect">
          <label htmlFor="recorder-num-speakers">Speakers</label>
          <input
            id="recorder-num-speakers"
            type="number"
            data-testid="recorder-num-speakers"
            min={1}
            max={10}
            placeholder="auto"
            value={numSpeakers}
            disabled={controlsLocked}
            onChange={(e) => setNumSpeakers(e.target.value)}
          />
        </div>
        <button
          type="button"
          data-testid="recorder-toggle"
          className={`${styles.toggleBtn} ${isListening ? styles.rec : ""}`}
          disabled={isBusy || !support.supported}
          onClick={handleToggle}
        >
          {isListening ? "Stop" : "Start"}
        </button>
        <button type="button" className={styles.button} onClick={clear}>
          Clear
        </button>
        <button
          type="button"
          className={styles.button}
          onClick={handleSave}
          disabled={state.turns.length === 0}
        >
          Save
        </button>
      </div>

      {!support.supported && (
        <div
          className={styles.unsupportedWarning}
          data-testid="recorder-unsupported-warning"
          role="alert"
        >
          {support.reason}
        </div>
      )}

      {state.backgrounded && (
        <div
          className={styles.backgroundWarning}
          data-testid="recorder-background-warning"
          role="status"
        >
          This tab is in the background or your screen is locked — some mobile browsers pause
          recording here. Keep this tab open and visible to avoid losing audio.
        </div>
      )}

      <main className={styles.main}>
        <TurnList turns={state.turns} partial={state.partial} />
      </main>
    </AppLayout>
  );
}
