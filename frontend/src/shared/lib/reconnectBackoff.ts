// Shared by useRecorderConnection and useTranslateConnection: both live
// sessions (mic capture over /ws and /ws/translate) reconnect a dropped
// WebSocket the same way, since a cellular blip shouldn't tear down an
// in-progress recording.
export const MAX_RECONNECT_ATTEMPTS = 5;

const BASE_DELAY_MS = 1000;
const MAX_DELAY_MS = 16000;

/** Exponential backoff delay in ms for the Nth reconnect attempt
 * (1-indexed): 1s, 2s, 4s, 8s, 16s, capped at MAX_DELAY_MS. */
export function reconnectDelayMs(attempt: number): number {
  return Math.min(BASE_DELAY_MS * 2 ** (attempt - 1), MAX_DELAY_MS);
}
