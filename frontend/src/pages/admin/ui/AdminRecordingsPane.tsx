import { useState, type ReactElement } from "react";
import { useAppSelector } from "@/app/hooks";
import {
  useGetRecordingsQuery,
  useLazyGetTranscriptQuery,
  useDeleteRecordingMutation,
} from "@/entities/recording/api/recordingsApi";
import type { Recording, RecordingSource } from "@/entities/recording/model/types";
import { RECORDING_SOURCE_LABELS } from "@/entities/recording/model/types";
import { RecordingSourceTag } from "@/entities/recording/ui/RecordingSourceTag";
import { useGetUsersQuery } from "@/entities/user/api/usersApi";
import { downloadAuthenticated, triggerBlobDownload } from "@/shared/lib/download";
import { fmtDate } from "@/shared/lib/fmtDate";
import { fmtDur } from "@/shared/lib/formatters";
import styles from "./AdminRecordingsPane.module.css";

function RecordingRow({
  recording,
  onError,
}: {
  recording: Recording;
  onError: (message: string | null) => void;
}): ReactElement {
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
      await downloadAuthenticated(
        `${window.location.origin}/api/recordings/${recording.id}/audio`,
        token,
        `${recording.id}.wav`,
      );
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
    <tr>
      <td>{fmtDate(recording.started_at)}</td>
      <td>{recording.username}</td>
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
          <button type="button" className={styles.danger} onClick={remove} disabled={isDeleting}>
            Delete
          </button>
        </div>
      </td>
    </tr>
  );
}

// Port of admin.html's "All recordings" tab - a full inline table across
// every user, unlike MyRecordingsPage.tsx's per-user /recordings page, but
// built on the same recordingsApi hooks and lib/download.ts utilities.
export function AdminRecordingsPane(): ReactElement {
  const [userId, setUserId] = useState("");
  const [source, setSource] = useState<RecordingSource | "">("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  // Reuses the Users tab's own query rather than issuing a second users
  // fetch just to populate the filter dropdown.
  const { data: users } = useGetUsersQuery();

  const {
    data: recordings,
    isLoading,
    isError,
    refetch,
  } = useGetRecordingsQuery({
    user_id: userId || undefined,
    source: source || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  });

  return (
    <div className={styles.panel}>
      <h2 className={styles.heading}>All recordings</h2>
      <div className={styles.filters}>
        <div>
          <label htmlFor="rec-filter-user">Filter by user</label>
          <select id="rec-filter-user" value={userId} onChange={(e) => setUserId(e.target.value)}>
            <option value="">All users</option>
            {users?.map((u) => (
              <option key={u.id} value={u.id}>
                {u.username}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="rec-filter-type">Type</label>
          <select
            id="rec-filter-type"
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
          <label htmlFor="rec-filter-from">From</label>
          <input
            id="rec-filter-from"
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="rec-filter-to">To</label>
          <input
            id="rec-filter-to"
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </div>
      </div>

      {isLoading && <div className={styles.empty}>Loading...</div>}

      {!isLoading && isError && (
        <div className={styles.errorState}>
          Couldn't load recordings.
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
              <th>User</th>
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
  );
}
