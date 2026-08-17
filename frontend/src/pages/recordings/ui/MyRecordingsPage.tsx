import { useState, type ReactElement } from "react";
import { useAppSelector } from "@/app/hooks";
import { AppLayout } from "@/widgets/app-layout/ui/AppLayout";
import {
  useGetRecordingsQuery,
  useLazyGetTranscriptQuery,
} from "@/entities/recording/api/recordingsApi";
import type { Recording, RecordingSource } from "@/entities/recording/model/types";
import { RECORDING_SOURCE_LABELS } from "@/entities/recording/model/types";
import { RecordingSourceTag } from "@/entities/recording/ui/RecordingSourceTag";
import { downloadAuthenticated, triggerBlobDownload } from "@/shared/lib/download";
import { fmtDate } from "@/shared/lib/fmtDate";
import { fmtDur } from "@/shared/lib/formatters";
import styles from "./MyRecordingsPage.module.css";

function RecordingRow({
  recording,
  onError,
}: {
  recording: Recording;
  onError: (message: string | null) => void;
}): ReactElement {
  const token = useAppSelector((s) => s.auth.token);
  const [getTranscript] = useLazyGetTranscriptQuery();

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
      await downloadAuthenticated(
        `${window.location.origin}/api/recordings/${recording.id}/audio`,
        token,
        `${recording.id}.wav`,
      );
    } catch {
      onError("Audio download failed");
    }
  }

  return (
    <tr>
      <td>{fmtDate(recording.started_at)}</td>
      <td>
        <RecordingSourceTag source={recording.source} />
      </td>
      <td>{fmtDur(recording.duration)}</td>
      <td>{recording.turn_count}</td>
      <td className={styles.preview}>{recording.preview || "—"}</td>
      <td>
        <div className={styles.rowActions}>
          <button type="button" onClick={downloadTranscript}>
            Transcript
          </button>
          <button type="button" onClick={downloadAudio}>
            Audio
          </button>
        </div>
      </td>
    </tr>
  );
}

// Full-page replacement for the old /app-hosted slide-out drawer
// (RecordingsDrawer, since deleted) - a dedicated route so a user's own
// recordings get the same full-width, filterable-table treatment
// AdminRecordingsPane gives every user's recordings on /admin, just scoped
// to the signed-in user (no user-filter dropdown needed).
export function MyRecordingsPage(): ReactElement {
  const user = useAppSelector((s) => s.auth.user)!;
  const [source, setSource] = useState<RecordingSource | "">("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  const {
    data: recordings,
    isLoading,
    isError,
    refetch,
  } = useGetRecordingsQuery({
    user_id: user.id,
    source: source || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  });

  return (
    <AppLayout user={user}>
      <main className={styles.main}>
        <div className={styles.panel}>
          <h2 className={styles.heading}>My recordings</h2>
          <div className={styles.filters}>
            <div>
              <label htmlFor="my-rec-filter-type">Type</label>
              <select
                id="my-rec-filter-type"
                value={source}
                onChange={(e) => setSource(e.target.value as RecordingSource | "")}
              >
                <option value="">All types</option>
                {(Object.keys(RECORDING_SOURCE_LABELS) as RecordingSource[]).map((s) => (
                  <option key={s} value={s}>
                    {RECORDING_SOURCE_LABELS[s]}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="my-rec-filter-from">From</label>
              <input
                id="my-rec-filter-from"
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="my-rec-filter-to">To</label>
              <input
                id="my-rec-filter-to"
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
              />
            </div>
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

          {!isLoading && !isError && recordings && recordings.length === 0 && (
            <div className={styles.empty}>No recordings yet.</div>
          )}

          {!isLoading && !isError && recordings && recordings.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Type</th>
                  <th>Length</th>
                  <th>Turns</th>
                  <th>Preview</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {recordings.map((r) => (
                  <RecordingRow key={r.id} recording={r} onError={setActionError} />
                ))}
              </tbody>
            </table>
          )}

          {actionError && <div className={styles.actionError}>{actionError}</div>}
        </div>
      </main>
    </AppLayout>
  );
}
