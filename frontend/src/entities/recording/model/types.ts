// Matches voice_transcriber/db.py::RECORDING_SOURCES.
export type RecordingSource = "transcribe" | "translate" | "upload";

export const RECORDING_SOURCE_LABELS: Record<RecordingSource, string> = {
  transcribe: "Recorded",
  translate: "Translated",
  upload: "Uploaded",
};

// GET /api/recordings item shape, verified against
// voice_transcriber/routes_api.py::_rec_json.
export interface Recording {
  id: string;
  username: string;
  user_id: string;
  /** ISO-8601 with an explicit UTC offset. */
  started_at: string;
  /** Seconds, server-rounded to 1 decimal. */
  duration: number;
  turn_count: number;
  preview: string;
  source: RecordingSource;
}

export interface RecordingsQuery {
  user_id?: string;
  date_from?: string;
  date_to?: string;
  source?: RecordingSource;
}
