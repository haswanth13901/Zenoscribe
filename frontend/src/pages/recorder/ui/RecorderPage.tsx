import type { ReactElement } from "react";
import { useAppSelector } from "@/app/hooks";
import { AppLayout } from "@/widgets/app-layout/ui/AppLayout";
import { useRecorderConnection } from "@/features/recorder/model/useRecorderConnection";
import { triggerBlobDownload } from "@/shared/lib/download";
import { turnsToText } from "@/features/recorder/lib/transcriptText";
import { TurnList } from "@/pages/recorder/ui/TurnList";
import styles from "./RecorderPage.module.css";

// Rendered only inside <RequireAuth>, so `user` is guaranteed non-null here.
export function RecorderPage(): ReactElement {
  const user = useAppSelector((s) => s.auth.user)!;
  const { state, start, stop, clear } = useRecorderConnection();

  const isListening = state.status === "listening";
  const isBusy = state.status === "connecting" || state.status === "authenticating";

  function handleToggle() {
    if (isListening) {
      stop();
    } else {
      start();
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
          className={`${styles.status} ${isListening ? styles.statusLive : ""} ${state.isError ? styles.statusError : ""}`}
        >
          {state.statusMessage === "idle" ? "" : state.statusMessage}
        </span>
        <button
          type="button"
          data-testid="recorder-toggle"
          className={`${styles.toggleBtn} ${isListening ? styles.rec : ""}`}
          disabled={isBusy}
          onClick={handleToggle}
        >
          {isListening ? "Stop" : "Start"}
        </button>
        <button type="button" onClick={clear}>
          Clear
        </button>
        <button type="button" onClick={handleSave} disabled={state.turns.length === 0}>
          Save
        </button>
      </div>

      <main className={styles.main}>
        <TurnList turns={state.turns} partial={state.partial} />
      </main>
    </AppLayout>
  );
}
