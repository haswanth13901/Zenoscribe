import { afterEach, describe, expect, it, vi } from "vitest";
import { checkAudioCaptureSupport } from "@/shared/lib/browserSupport";

describe("checkAudioCaptureSupport", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("supported when getUserMedia, AudioContext, and a secure context are all present", () => {
    vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia: vi.fn() } });
    vi.stubGlobal("AudioContext", class {});
    expect(checkAudioCaptureSupport()).toEqual({ supported: true, reason: null });
  });

  it("unsupported over an insecure context, regardless of API presence", () => {
    vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia: vi.fn() } });
    vi.stubGlobal("AudioContext", class {});
    vi.stubGlobal("window", { ...window, isSecureContext: false });
    const result = checkAudioCaptureSupport();
    expect(result.supported).toBe(false);
    expect(result.reason).toContain("HTTPS");
  });

  it("unsupported when getUserMedia is missing", () => {
    vi.stubGlobal("navigator", { ...navigator, mediaDevices: {} });
    vi.stubGlobal("AudioContext", class {});
    const result = checkAudioCaptureSupport();
    expect(result.supported).toBe(false);
    expect(result.reason).toContain("microphone");
  });

  it("unsupported when neither AudioContext nor webkitAudioContext exists", () => {
    vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia: vi.fn() } });
    vi.stubGlobal("AudioContext", undefined);
    const result = checkAudioCaptureSupport();
    expect(result.supported).toBe(false);
    expect(result.reason).toContain("Web Audio");
  });

  it("supported via the webkit-prefixed constructor alone", () => {
    vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia: vi.fn() } });
    vi.stubGlobal("AudioContext", undefined);
    vi.stubGlobal("webkitAudioContext", class {});
    expect(checkAudioCaptureSupport().supported).toBe(true);
  });
});
