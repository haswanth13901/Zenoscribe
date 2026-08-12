import { useEffect, useState, type ReactElement } from "react";
import { useSearchParams } from "react-router-dom";
import { useAppSelector } from "../../app/hooks";
import { AppLayout } from "../../components/layout/AppLayout";
import { useRecorderConnection } from "../../features/recorder/useRecorderConnection";
import { triggerBlobDownload } from "../../lib/download";
import { turnsToText } from "../../lib/transcriptText";
import { UploadPanel } from "../../features/transcribe/UploadPanel";
import { RecordingsDrawer } from "./RecordingsDrawer";
import { TurnList } from "./TurnList";
import styles from "./RecorderPage.module.css";

// Rendered only inside <RequireAuth>, so `user` is guaranteed non-null here.
export function RecorderPage(): ReactElement {
  const user = useAppSelector((s) => s.auth.user)!;
  const { state, start, stop, clear } = useRecorderConnection();
  const [searchParams, setSearchParams] = useSearchParams();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);

  // Deep-links from the sidebar (?recordings=1, ?upload=1) - the param is
  // cleared right after acting so a repeat click while already on /app
  // (no location change otherwise) still re-opens the panel; see the plan.
  useEffect(() => {
    let changed = false;
    if (searchParams.get("recordings") === "1") {
      setDrawerOpen(true);
      changed = true;
    }
    if (searchParams.get("upload") === "1") {
      setUploadOpen(true);
      changed = true;
    }
    if (changed) {
      setSearchParams(
        (prev) => {
          prev.delete("recordings");
          prev.delete("upload");
          return prev;
        },
        { replace: true },
      );
    }
  }, [searchParams, setSearchParams]);

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
    triggerBlobDownload(new Blob([turnsToText(state.turns)], { type: "text/plain" }), `transcript-${Date.now()}.txt`);
  }

  return (
    <AppLayout user={user}>
      <div className={styles.toolbar}>
        <span
          data-testid="recorder-status"
          className={`${styles.status} ${isListening ? styles.statusLive : ""} ${state.isError ? styles.statusError : ""}`}
        >
          {state.statusMessage}
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

      <UploadPanel open={uploadOpen} onClose={() => setUploadOpen(false)} />
      <RecordingsDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </AppLayout>
  );
}
