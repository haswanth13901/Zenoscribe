export interface AudioCaptureSupport {
  supported: boolean;
  /** Human-readable reason to show the user, set only when unsupported. */
  reason: string | null;
}

const UPGRADE_HINT = "Try a recent version of Chrome, Edge, Firefox, or Safari 14.5+.";

/** Thrown by useRecorderConnection/useTranslateConnection when a
 * successfully constructed AudioContext still lacks .audioWorklet (some
 * older-but-not-ancient browsers, e.g. Safari 14.0-14.4) - replaces the
 * cryptic native "Cannot read properties of undefined" TypeError that
 * `ctx.audioWorklet.addModule(...)` would otherwise throw. Checked on the
 * instance, not statically via checkAudioCaptureSupport(), because a
 * prototype-level check can't reliably distinguish real implementations
 * from this project's own test stand-ins. */
export const AUDIO_WORKLET_UNSUPPORTED_MESSAGE = `This browser doesn't support AudioWorklet, which live audio capture needs. ${UPGRADE_HINT}`;

/** Proactive, page-load-time check for the APIs live recording/translation
 * depend on (mic capture, Web Audio), run once per page render rather than
 * waiting for the user to click Start and hit a cryptic native error. Does
 * NOT check AudioWorklet specifically - that's still verified where the
 * AudioContext instance is actually constructed (see
 * useRecorderConnection/useTranslateConnection), since a static prototype
 * check can't reliably tell a real browser's implementation from this
 * project's own test stand-ins. */
export function checkAudioCaptureSupport(): AudioCaptureSupport {
  if (typeof window === "undefined" || typeof navigator === "undefined") {
    return { supported: false, reason: `This browser isn't supported. ${UPGRADE_HINT}` };
  }
  if (window.isSecureContext === false) {
    return {
      supported: false,
      reason:
        "Live audio capture requires a secure connection (HTTPS). This page was loaded over an insecure connection.",
    };
  }
  if (typeof navigator.mediaDevices?.getUserMedia !== "function") {
    return {
      supported: false,
      reason: `This browser doesn't support microphone capture. ${UPGRADE_HINT}`,
    };
  }
  const webkitAudioContext = (window as unknown as { webkitAudioContext?: unknown })
    .webkitAudioContext;
  const hasAudioContext =
    typeof window.AudioContext === "function" || typeof webkitAudioContext === "function";
  if (!hasAudioContext) {
    return {
      supported: false,
      reason: `This browser doesn't support the Web Audio API, which live audio capture needs. ${UPGRADE_HINT}`,
    };
  }
  return { supported: true, reason: null };
}
