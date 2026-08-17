import { useRef, useState, type ReactElement } from "react";
import type { SerializedError } from "@reduxjs/toolkit";
import type { FetchBaseQueryError } from "@reduxjs/toolkit/query";
import { useGetLanguagesQuery } from "@/entities/language/api/languagesApi";
import { extractApiError } from "@/shared/lib/apiError";
import {
  useTranscribeTranslateMutation,
  type TranscribeTurn,
} from "@/features/transcribe/api/transcribeApi";
import { TranscriptTurns } from "@/features/transcribe/ui/TranscriptTurns";
import styles from "./UploadPanel.module.css";

interface UploadPanelProps {
  open: boolean;
}

const FALLBACK_LANGUAGES = [{ code: "en", name: "English" }];

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

// Port of upload.js's batch-transcribe widget, now mounted only by
// UploadPage.tsx (/upload) - kept as its own open-driven component rather
// than inlined there, since UploadPanel.test.tsx's full behavioral coverage
// stays independent of wherever it's mounted. Auto-opening the
// native file picker (as the original's uploadBtn.onclick did) isn't
// reliably possible from a route-change effect - browsers only allow it
// synchronously inside a real click handler - so this shows a visible
// "Choose file" trigger instead, a deliberate small UX adaptation, not a
// missed port.
export function UploadPanel({ open }: UploadPanelProps): ReactElement | null {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [targetLanguage, setTargetLanguage] = useState("en");
  const [numSpeakers, setNumSpeakers] = useState("");
  const [transcribeResult, setTranscribeResult] = useState<TranscribeTurn[] | null>(null);
  const [translateResult, setTranslateResult] = useState<TranscribeTurn[] | null>(null);

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

  function parsedNumSpeakers(): number | undefined {
    const n = parseInt(numSpeakers, 10);
    return Number.isFinite(n) && n > 0 ? n : undefined;
  }

  async function doTranscribe() {
    if (!file) return;
    setTranscribeResult(null);
    try {
      const json = await transcribe({ file, numSpeakers: parsedNumSpeakers() }).unwrap();
      setTranscribeResult(json.turns);
    } catch {
      // transcribeState.isError renders the error below.
    }
  }

  async function doTranscribeAndTranslate() {
    if (!file) return;
    setTranslateResult(null);
    try {
      const json = await transcribeAndTranslate({
        file,
        targetLanguage,
        numSpeakers: parsedNumSpeakers(),
      }).unwrap();
      setTranslateResult(json.turns);
    } catch {
      // translateState.isError renders the error below.
    }
  }

  function handleReset() {
    setFile(null);
    setTargetLanguage("en");
    setNumSpeakers("");
    setTranscribeResult(null);
    setTranslateResult(null);
    transcribeState.reset();
    translateState.reset();
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  return (
    <div className={styles.panel}>
      <div className={styles.card}>
        <div className={styles.head}>
          <strong>Transcribe a file</strong>
          <button type="button" className={styles.button} onClick={handleReset}>
            Reset
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
        <button type="button" className={styles.button} onClick={() => fileInputRef.current?.click()}>
          Choose file
        </button>
        {file && (
          <div className={styles.filename}>
            Selected: {file.name} ({Math.round(file.size / 1024)} KB)
          </div>
        )}

        <div className={styles.row}>
          <div className={styles.field} title="Optional hint for how many distinct voices to expect">
            <label htmlFor="upload-num-speakers">Speakers</label>
            <input
              id="upload-num-speakers"
              type="number"
              data-testid="upload-num-speakers"
              min={1}
              max={10}
              placeholder="auto"
              value={numSpeakers}
              onChange={(e) => setNumSpeakers(e.target.value)}
            />
          </div>
          <button
            type="button"
            className={styles.button}
            onClick={doTranscribe}
            disabled={!file || transcribeState.isLoading}
          >
            {transcribeState.isLoading ? "Transcribing..." : "Transcribe"}
          </button>
          <div className={styles.field}>
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
          <button
            type="button"
            className={styles.button}
            onClick={doTranscribeAndTranslate}
            disabled={!file || translateState.isLoading}
          >
            {translateState.isLoading
              ? "Transcribing & translating..."
              : "Transcribe & Translate"}
          </button>
        </div>

        {transcribeResult && (
          <TranscriptTurns turns={transcribeResult} emptyText="(no transcription)" />
        )}
        {transcribeState.isError && (
          <div className={styles.errorText} data-testid="upload-transcribe-error">
            {formatUploadError(transcribeState.error)}
          </div>
        )}

        {translateResult && <TranscriptTurns turns={translateResult} emptyText="(no translation)" />}
        {translateState.isError && (
          <div className={styles.errorText} data-testid="upload-translate-error">
            {formatUploadError(translateState.error)}
          </div>
        )}
      </div>
    </div>
  );
}
