import { useCallback, useMemo, useState, type ReactElement } from "react";
import { useAppSelector } from "@/app/hooks";
import { AppLayout } from "@/widgets/app-layout/ui/AppLayout";
import { useGetLanguagesQuery } from "@/entities/language/api/languagesApi";
import { useElapsedTimer } from "@/features/translate/model/useElapsedTimer";
import { useTranslateConnection } from "@/features/translate/model/useTranslateConnection";
import type { TranslateMode, TranslateSettings } from "@/features/translate/model/types";
import { checkAudioCaptureSupport } from "@/shared/lib/browserSupport";
import { TranscriptView, type ViewMode } from "@/pages/translate/ui/TranscriptView";
import styles from "./TranslatePage.module.css";

const VIEW_STORAGE_KEY = "zeno-view";

function readStoredView(): ViewMode {
  try {
    const saved = localStorage.getItem(VIEW_STORAGE_KEY);
    return saved === "columns" || saved === "focus" ? saved : "stacked";
  } catch {
    return "stacked";
  }
}

// Rendered only inside <RequireAuth>, so `user` is guaranteed non-null here.
export function TranslatePage(): ReactElement {
  const user = useAppSelector((s) => s.auth.user)!;
  const { state, start, stop, restart } = useTranslateConnection();
  const elapsed = useElapsedTimer(state.status === "listening");
  // Checked once per mount rather than waiting for a Start click to hit a
  // cryptic native error - browser capabilities don't change mid-session.
  const support = useMemo(() => checkAudioCaptureSupport(), []);

  const { data: languagesData } = useGetLanguagesQuery();
  const languages = useMemo(() => languagesData?.languages ?? [], [languagesData]);
  const voices = languagesData?.voices ?? [];

  const [mode, setModeState] = useState<TranslateMode>("one_way");
  const [targetLanguage, setTargetLanguage] = useState("en");
  const [languageA, setLanguageA] = useState("en");
  const [languageB, setLanguageB] = useState("es");
  const [voice, setVoice] = useState("");
  const [speak, setSpeak] = useState(false);
  const [diarize, setDiarize] = useState(false);
  const [numSpeakers, setNumSpeakers] = useState("");
  const [view, setView] = useState<ViewMode>(readStoredView);

  const effectiveVoice = voice || voices[0] || "Maya";
  const isBusy = state.status === "connecting";
  const isRunning = state.status === "listening" || state.status === "connecting";
  // Matches lockControls() exactly - #speak is included, #diarize
  // deliberately is not (an existing minor inconsistency in the original:
  // diarize has no effect once the hello frame is sent, but stays editable).
  const controlsLocked = isRunning;

  const langName = useCallback(
    (code: string | null): string => {
      if (!code) return "";
      return languages.find((l) => l.code === code)?.name ?? code;
    },
    [languages],
  );

  function setMode(m: TranslateMode) {
    if (isRunning) return; // matches setMode()'s `if (running) return;` guard
    setModeState(m);
  }

  function currentSettings(): TranslateSettings {
    const n = parseInt(numSpeakers, 10);
    return {
      mode,
      speak,
      voice: effectiveVoice,
      diarize,
      numSpeakers: Number.isFinite(n) && n > 0 ? n : undefined,
      targetLanguage,
      languageA,
      languageB,
    };
  }

  function handleToggle() {
    if (state.status === "listening" || state.status === "connecting") {
      stop();
    } else {
      start(currentSettings());
    }
  }

  function handleRestart() {
    restart(currentSettings());
  }

  function changeView(v: ViewMode) {
    setView(v);
    try {
      localStorage.setItem(VIEW_STORAGE_KEY, v);
    } catch {
      // Ignore - worst case the choice doesn't persist across reloads.
    }
  }

  return (
    <AppLayout user={user}>
      <div className={styles.toolbar}>
        <span
          data-testid="translate-status"
          className={`${styles.status} ${state.status === "listening" && !state.reconnecting ? styles.statusLive : ""} ${state.reconnecting ? styles.statusWarn : ""} ${state.isError ? styles.statusError : ""}`}
        >
          {state.status === "listening" && elapsed
            ? `${state.statusMessage} · ${elapsed}`
            : state.statusMessage === "idle"
              ? ""
              : state.statusMessage}
        </span>
      </div>

      <div className={styles.controls}>
        <div className={styles.row1}>
          <div className={styles.field}>
            <label>Mode</label>
            <div className={styles.modes}>
              <button
                type="button"
                data-testid="mode-one-way"
                className={mode === "one_way" ? styles.on : undefined}
                disabled={isRunning}
                onClick={() => setMode("one_way")}
              >
                Auto-detect → one language
              </button>
              <button
                type="button"
                data-testid="mode-two-way"
                className={mode === "two_way" ? styles.on : undefined}
                disabled={isRunning}
                onClick={() => setMode("two_way")}
              >
                Two-way
              </button>
            </div>
          </div>

          {mode === "one_way" && (
            <div className={styles.field}>
              <label htmlFor="target-language">Translate into</label>
              <select
                id="target-language"
                value={targetLanguage}
                disabled={controlsLocked}
                onChange={(e) => setTargetLanguage(e.target.value)}
              >
                {languages.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.name}
                  </option>
                ))}
              </select>
              <div className={styles.hint}>
                Speak a different language than this. The translation appears on the right.
              </div>
            </div>
          )}

          {mode === "two_way" && (
            <>
              <div className={styles.field}>
                <label htmlFor="language-a">Language A</label>
                <select
                  id="language-a"
                  value={languageA}
                  disabled={controlsLocked}
                  onChange={(e) => setLanguageA(e.target.value)}
                >
                  {languages.map((l) => (
                    <option key={l.code} value={l.code}>
                      {l.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className={styles.field}>
                <label htmlFor="language-b">Language B</label>
                <select
                  id="language-b"
                  value={languageB}
                  disabled={controlsLocked}
                  onChange={(e) => setLanguageB(e.target.value)}
                >
                  {languages.map((l) => (
                    <option key={l.code} value={l.code}>
                      {l.name}
                    </option>
                  ))}
                </select>
              </div>
            </>
          )}

          <div className={styles.field}>
            <label htmlFor="translate-voice">Voice</label>
            <select
              id="translate-voice"
              value={effectiveVoice}
              disabled={controlsLocked}
              onChange={(e) => setVoice(e.target.value)}
            >
              {voices.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </div>

          <div className={styles.field} title="Optional hint for how many distinct voices to expect">
            <label htmlFor="translate-num-speakers">Speakers</label>
            <input
              id="translate-num-speakers"
              type="number"
              data-testid="translate-num-speakers"
              min={1}
              max={10}
              placeholder="auto"
              value={numSpeakers}
              disabled={controlsLocked}
              onChange={(e) => setNumSpeakers(e.target.value)}
            />
          </div>
        </div>

        <div className={styles.row2}>
          <label className={styles.toggleField}>
            <input
              type="checkbox"
              className={styles.toggleInput}
              checked={speak}
              disabled={controlsLocked}
              onChange={(e) => setSpeak(e.target.checked)}
            />
            <span className={styles.track}>
              <span className={styles.thumb} />
            </span>
            Speak translation
          </label>
          <label
            className={styles.toggleField}
            title="Best in two-way mode with clear turn-taking and separate mics"
          >
            <input
              type="checkbox"
              className={styles.toggleInput}
              checked={diarize}
              onChange={(e) => setDiarize(e.target.checked)}
            />
            <span className={styles.track}>
              <span className={styles.thumb} />
            </span>
            Label speakers
          </label>

          <div className={styles.viewSwitch}>
            <button
              type="button"
              data-testid="view-columns"
              className={view === "columns" ? styles.on : undefined}
              onClick={() => changeView("columns")}
            >
              Columns
            </button>
            <button
              type="button"
              data-testid="view-stacked"
              className={view === "stacked" ? styles.on : undefined}
              onClick={() => changeView("stacked")}
            >
              Stacked
            </button>
            <button
              type="button"
              data-testid="view-focus"
              className={view === "focus" ? styles.on : undefined}
              onClick={() => changeView("focus")}
            >
              Focus
            </button>
          </div>

          <div className={styles.spacer} />
          <button
            type="button"
            data-testid="translate-restart"
            className={styles.button}
            title="Clear the transcript and start a fresh session"
            disabled={state.statusMessage === "restarting"}
            onClick={handleRestart}
          >
            Restart
          </button>
          <button
            type="button"
            data-testid="translate-toggle"
            className={`${styles.toggleBtn} ${state.status === "listening" ? styles.rec : ""}`}
            disabled={isBusy || !support.supported}
            onClick={handleToggle}
          >
            {state.status === "listening" ? "Stop" : "Start"}
          </button>
        </div>
      </div>

      {!support.supported && (
        <div
          className={styles.unsupportedWarning}
          data-testid="translate-unsupported-warning"
          role="alert"
        >
          {support.reason}
        </div>
      )}

      {state.backgrounded && (
        <div
          className={styles.backgroundWarning}
          data-testid="translate-background-warning"
          role="status"
        >
          This tab is in the background or your screen is locked — some
          mobile browsers pause the session here. Keep this tab open and
          visible to avoid losing audio.
        </div>
      )}

      <main className={styles.main}>
        <TranscriptView utterances={state.utterances} view={view} langName={langName} />
      </main>
    </AppLayout>
  );
}
