import { useState, type ReactElement } from "react";
import { useAppSelector } from "../../app/hooks";
import { useDeleteRecordingMutation, useGetRecordingsQuery, useLazyGetTranscriptQuery } from "../../features/recordings/recordingsApi";
import type { Recording } from "../../features/recordings/types";
import { downloadAuthenticated, triggerBlobDownload } from "../../lib/download";
import { fmtDur } from "../../lib/formatters";
import styles from "./RecordingsDrawer.module.css";

interface RecordingsDrawerProps {
  open: boolean;
  onClose: () => void;
}

function RecordingCard({ recording, onError }: { recording: Recording; onError: (message: string | null) => void }): ReactElement {
  const token = useAppSelector((s) => s.auth.token);
  const [getTranscript] = useLazyGetTranscriptQuery();
  const [deleteRecording, { isLoading: isDeleting }] = useDeleteRecordingMutation();

  async function downloadTranscript() {
    onError(null);
    try {
      const d = await getTranscript(recording.id).unwrap();
      triggerBlobDownload(new Blob([d.text], { type: "text/plain" }), `${recording.id}.txt`);
    } catch {
      onError("Transcript download failed");
    }
  }

  async function downloadAudio() {
    onError(null);
    try {
      await downloadAuthenticated(`${window.location.origin}/api/recordings/${recording.id}/audio`, token, `${recording.id}.wav`);
    } catch {
      onError("Audio download failed");
    }
  }

  async function remove() {
    if (!window.confirm("Delete this recording?")) return;
    onError(null);
    try {
      await deleteRecording(recording.id).unwrap();
    } catch {
      onError("Delete failed");
    }
  }

  return (
    <div className={styles.card}>
      <div className={styles.meta}>
        {new Date(recording.started_at).toLocaleString()} &middot; {fmtDur(recording.duration)} &middot; {recording.turn_count} turns
      </div>
      <div className={styles.preview}>{recording.preview || "(no speech detected)"}</div>
      <div className={styles.actions}>
        <button type="button" onClick={downloadTranscript}>
          Transcript
        </button>
        <button type="button" onClick={downloadAudio}>
          Audio
        </button>
        <button type="button" onClick={remove} disabled={isDeleting}>
          Delete
        </button>
      </div>
    </div>
  );
}

// Port of index.html's #drawer "My recordings" panel. Loading/error+retry/
// empty/list precedence matches RecentSessions.tsx's established pattern -
// the original's `catch (e) { list.innerHTML = escapeHtml(e.message) }` was
// visually indistinguishable from the empty state and had no retry.
export function RecordingsDrawer({ open, onClose }: RecordingsDrawerProps): ReactElement | null {
  const user = useAppSelector((s) => s.auth.user)!;
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  const {
    data: recordings,
    isLoading,
    isError,
    refetch,
  } = useGetRecordingsQuery({ user_id: user.id, date_from: dateFrom || undefined, date_to: dateTo || undefined }, { skip: !open });

  if (!open) return null;

  function clearFilters() {
    setDateFrom("");
    setDateTo("");
  }

  return (
    <aside className={styles.drawer}>
      <div className={styles.head}>
        <strong>My recordings</strong>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </div>
      <div className={styles.filters}>
        <div>
          <label htmlFor="drawer-date-from">From</label>
          <input id="drawer-date-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </div>
        <div>
          <label htmlFor="drawer-date-to">To</label>
          <input id="drawer-date-to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>
        <button type="button" onClick={clearFilters}>
          Clear
        </button>
      </div>

      {isLoading && <div className={styles.empty}>Loading...</div>}

      {!isLoading && isError && (
        <div className={styles.errorState}>
          Couldn't load your recordings.
          <button type="button" className={styles.retryBtn} onClick={refetch}>
            Try again
          </button>
        </div>
      )}

      {!isLoading && !isError && recordings && recordings.length === 0 && <div className={styles.empty}>No recordings yet.</div>}

      {!isLoading && !isError && recordings && recordings.length > 0 && (
        <div>
          {recordings.map((r) => (
            <RecordingCard key={r.id} recording={r} onError={setActionError} />
          ))}
        </div>
      )}

      {actionError && <div className={styles.actionError}>{actionError}</div>}
    </aside>
  );
}
