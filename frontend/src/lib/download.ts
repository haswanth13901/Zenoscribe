// Consolidates the blob-download logic index.html had duplicated between
// dl() and the Save button's inline handler.
export function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// For binary/file responses (e.g. GET /api/recordings/{id}/audio) that
// aren't JSON - deliberately not routed through RTK Query's JSON-first
// fetchBaseQuery, matching the original's own raw-fetch approach for the
// same reason.
export async function downloadAuthenticated(url: string, token: string | null, filename: string): Promise<void> {
  const r = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!r.ok) throw new Error("Download failed");
  triggerBlobDownload(await r.blob(), filename);
}
