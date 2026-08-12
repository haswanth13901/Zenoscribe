import type { SerializedError } from "@reduxjs/toolkit";
import type { FetchBaseQueryError } from "@reduxjs/toolkit/query";

export interface ApiErrorInfo {
  /** HTTP status, when the failure was an actual server response. */
  status?: number;
  /** The server's `detail` message (FastAPI's default HTTPException body),
   * or a network/serialization-level message when there was no response. */
  message: string;
}

// Extracts status+message from an RTK Query mutation/query error - the one
// place that knows how to narrow FetchBaseQueryError's status/data union.
// Callers format the display string themselves (admin.html's user-facing
// errors were always plain server detail text with no status code, e.g.
// "Cannot deactivate yourself"; the upload panel's alert() used to show
// status too, e.g. "Upload failed: 504 ...") - this only centralizes the
// extraction, not the phrasing.
export function extractApiError(
  error: FetchBaseQueryError | SerializedError | undefined,
  fallback = "Request failed.",
): ApiErrorInfo {
  if (!error) return { message: fallback };
  if ("status" in error) {
    if (typeof error.status === "number") {
      const data = error.data;
      const detail = data && typeof data === "object" && "detail" in data ? String((data as { detail: unknown }).detail) : undefined;
      return { status: error.status, message: detail ?? fallback };
    }
    return { message: error.error };
  }
  return { message: error.message ?? "unknown error" };
}
