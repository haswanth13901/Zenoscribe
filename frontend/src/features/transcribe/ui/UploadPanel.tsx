import { useRef, useState, type ReactElement } from "react";
import type { SerializedError } from "@reduxjs/toolkit";
import type { FetchBaseQueryError } from "@reduxjs/toolkit/query";
import { useGetLanguagesQuery } from "@/entities/language/api/languagesApi";
import { extractApiError } from "@/shared/lib/apiError";
import { useTranscribeTranslateMutation } from "@/features/transcribe/api/transcribeApi";
import styles from "./UploadPanel.module.css";

interface UploadPanelProps {
  open: boolean;
  onClose: () => void;
}

const FALLBACK_LANGUAGES = [{ code: "en", name: "English" }];

function joinTurns(turns: { text: string }[]): string {
  return turns
    .map((t) => t.text || "")
    .join(" ")
    .trim();
}

// The original showed the raw fetch failure via alert('Upload failed: ' +
// status + ' ' + text) - replaced with inline UI (no alert()), but keeping
// the same diagnostic value (status + server-provided detail) rather than
// collapsing every failure into one generic, undifferentiated message.
function formatUploadError(error: FetchBaseQueryError | SerializedError | undefined): string {
  const { status, message } = extractApiError(error, "Transcription failed.");
  return status
    ? `Transcription failed (${status}): ${message}`
    : `Transcription failed: ${message}`;
}

// Port of upload.js's batch-transcribe widget, shared by /app (the
// recorder) and /admin, both opened via a ?upload=1 deep-link instead of a
// page-owned #uploadBtn. Auto-opening the native file picker (as the
// original's uploadBtn.onclick did) isn't reliably possible from a
// route-change effect - browsers only allow it synchronously inside a real
// click handler - so this shows a visible "Choose file" trigger instead, a
// deliberate small UX adaptation, not a missed port.
export function UploadPanel({ open, onClose }: UploadPanelProps): ReactElement | null {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [targetLanguage, setTargetLanguage] = useState("en");
  const [transcribeResult, setTranscribeResult] = useState<string | null>(null);
  const [translateResult, setTranslateResult] = useState<string | null>(null);

  const { data: languagesData, isError: languagesError } = useGetLanguagesQuery(undefined, {
    skip: !open,
  });
  const languages = languagesError || !languagesData ? FALLBACK_LANGUAGES : languagesData.languages;

  const [transcribe, transcribeState] = useTranscribeTranslateMutation();
  const [transcribeAndTranslate, translateState] = useTranscribeTranslateMutation();

  if (!open) return null;

  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0] ?? null;
    setFile(picked);
    setTranscribeResult(null);
    setTranslateResult(null);
  }

  async function doTranscribe() {
    if (!file) return;
    setTranscribeResult(null);
    try {
      const json = await transcribe({ file }).unwrap();
      setTranscribeResult(joinTurns(json.turns) || "(no transcription)");
    } catch {
      // transcribeState.isError renders the error below.
    }
  }

  async function doTranscribeAndTranslate() {
    if (!file) return;
    setTranslateResult(null);
    try {
      const json = await transcribeAndTranslate({ file, targetLanguage }).unwrap();
      setTranslateResult(joinTurns(json.turns) || "(no translation)");
    } catch {
      // translateState.isError renders the error below.
    }
  }

  return (
    <div className={styles.panel}>
      <div className={styles.card}>
        <div className={styles.head}>
          <strong>Transcribe a file</strong>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>

        <input
          ref={fileInputRef}
          type="file"
          accept="audio/*"
          hidden
          onChange={onFileChange}
          data-testid="upload-file-input"
        />
        <button type="button" onClick={() => fileInputRef.current?.click()}>
          Choose file
        </button>
        {file && (
          <div className={styles.filename}>
            Selected: {file.name} ({Math.round(file.size / 1024)} KB)
          </div>
        )}

        <div className={styles.row}>
          <div className={styles.langField}>
            <label htmlFor="upload-lang">Translate (target language)</label>
            <select
              id="upload-lang"
              value={targetLanguage}
              onChange={(e) => setTargetLanguage(e.target.value)}
            >
              {languages.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <button
              type="button"
              onClick={doTranscribe}
              disabled={!file || transcribeState.isLoading}
            >
              {transcribeState.isLoading ? "Transcribing..." : "Transcribe"}
            </button>
            <button
              type="button"
              onClick={doTranscribeAndTranslate}
              disabled={!file || translateState.isLoading}
            >
              {translateState.isLoading
                ? "Transcribing & translating..."
                : "Transcribe & Translate"}
            </button>
          </div>
        </div>

        {transcribeResult && <div className={styles.result}>{transcribeResult}</div>}
        {transcribeState.isError && (
          <div className={styles.errorText} data-testid="upload-transcribe-error">
            {formatUploadError(transcribeState.error)}
          </div>
        )}

        {translateResult && <div className={styles.result}>{translateResult}</div>}
        {translateState.isError && (
          <div className={styles.errorText} data-testid="upload-translate-error">
            {formatUploadError(translateState.error)}
          </div>
        )}
      </div>
    </div>
  );
}
