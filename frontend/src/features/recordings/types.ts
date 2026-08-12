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
}

export interface RecordingsQuery {
  user_id?: string;
  date_from?: string;
  date_to?: string;
}
