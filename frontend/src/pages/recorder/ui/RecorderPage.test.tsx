import { configureStore } from "@reduxjs/toolkit";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { baseApi } from "@/shared/api/baseApi";
import authReducer, { setCredentials } from "@/features/auth/model/authSlice";
import type { AuthUser } from "@/features/auth/model/types";
import { RecorderPage } from "@/pages/recorder/ui/RecorderPage";

const user: AuthUser = { id: "u1", username: "ada", full_name: "Ada Lovelace", role: "user" };

function makeStore() {
  const store = configureStore({
    reducer: { auth: authReducer, [baseApi.reducerPath]: baseApi.reducer },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(baseApi.middleware),
  });
  store.dispatch(setCredentials({ token: "tok", user }));
  return store;
}

function renderRecorderPage(initialPath = "/app") {
  return render(
    <Provider store={makeStore()}>
      <MemoryRouter initialEntries={[initialPath]}>
        <RecorderPage />
      </MemoryRouter>
    </Provider>,
  );
}

// jsdom implements neither the WebSocket, AudioContext, nor
// AudioWorkletNode browser APIs the recorder depends on - stubbed here so
// this file can smoke-test the page's wiring. Deep connection-state-machine
// coverage lives in recorderReducer.test.ts, which needs none of this.
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
  binaryType = "";
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  send = vi.fn();
  close = vi.fn();
  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }
}

class FakeAudioContext {
  audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) };
  createMediaStreamSource = vi.fn(() => ({ connect: vi.fn() }));
  close = vi.fn().mockResolvedValue(undefined);
}

class FakeAudioWorkletNode {
  port = { onmessage: null };
  disconnect = vi.fn();
}

describe("RecorderPage", () => {
  let getUserMedia: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal("AudioContext", FakeAudioContext);
    vi.stubGlobal("AudioWorkletNode", FakeAudioWorkletNode);
    getUserMedia = vi.fn().mockReturnValue(new Promise(() => {})); // never resolves - we only assert it was called
    vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia } });
  });

  it("renders the toolbar and empty transcript", () => {
    renderRecorderPage();
    expect(screen.getByRole("button", { name: "Start" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.getByText("Press Start and speak.")).toBeInTheDocument();
    expect(screen.getByText("idle")).toBeInTheDocument();
  });

  it("Save is disabled with no turns", () => {
    renderRecorderPage();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("clicking Start requests the microphone with the expected constraints and opens a WebSocket to /ws", async () => {
    renderRecorderPage();
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(getUserMedia).toHaveBeenCalledWith({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: false,
      },
    });
    await waitFor(() => expect(screen.getByText("connecting")).toBeInTheDocument());
  });

  it("opens the recordings drawer via the ?recordings=1 deep-link", async () => {
    renderRecorderPage("/app?recordings=1");
    // The sidebar also has a "My recordings" button, so assert on
    // something unique to the open drawer itself.
    await waitFor(() => expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument());
  });

  it("opens the upload panel via the ?upload=1 deep-link", async () => {
    renderRecorderPage("/app?upload=1");
    await waitFor(() => expect(screen.getByText("Transcribe a file")).toBeInTheDocument());
  });
});
