import { configureStore } from "@reduxjs/toolkit";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { baseApi } from "@/shared/api/baseApi";
import authReducer, { setCredentials } from "@/features/auth/model/authSlice";
import type { AuthUser } from "@/features/auth/model/types";
import { TranslatePage } from "@/pages/translate/ui/TranslatePage";

const user: AuthUser = { id: "u1", username: "ada", full_name: "Ada Lovelace", role: "user" };

function makeStore() {
  const store = configureStore({
    reducer: { auth: authReducer, [baseApi.reducerPath]: baseApi.reducer },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(baseApi.middleware),
  });
  store.dispatch(setCredentials({ token: "tok", user }));
  return store;
}

function renderTranslatePage() {
  return render(
    <Provider store={makeStore()}>
      <MemoryRouter initialEntries={["/translate"]}>
        <TranslatePage />
      </MemoryRouter>
    </Provider>,
  );
}

// jsdom implements neither WebSocket, AudioContext, AudioWorkletNode, nor
// getUserMedia - stubbed here so this file can smoke-test the page's
// wiring. Deep connection-state-machine coverage lives in
// translateReducer.test.ts, which needs none of this.
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

describe("TranslatePage", () => {
  let getUserMedia: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal("AudioContext", FakeAudioContext);
    vi.stubGlobal("AudioWorkletNode", FakeAudioWorkletNode);
    getUserMedia = vi.fn().mockReturnValue(new Promise(() => {})); // never resolves - we only assert it was called
    vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia } });
  });

  it("renders the toolbar idle, defaulting to one-way mode", () => {
    renderTranslatePage();
    expect(screen.getByTestId("translate-status")).toHaveTextContent("idle");
    expect(screen.getByTestId("translate-toggle")).toHaveTextContent("Start");
    expect(screen.getByLabelText("Translate into")).toBeInTheDocument();
    expect(screen.queryByLabelText("Language A")).not.toBeInTheDocument();
  });

  it("switches to two-way mode, swapping the language fields", async () => {
    renderTranslatePage();
    await userEvent.click(screen.getByTestId("mode-two-way"));
    expect(screen.queryByLabelText("Translate into")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Language A")).toBeInTheDocument();
    expect(screen.getByLabelText("Language B")).toBeInTheDocument();
  });

  it("clicking Start requests the microphone with the expected constraints and opens a WebSocket to /ws/translate", async () => {
    renderTranslatePage();
    await userEvent.click(screen.getByTestId("translate-toggle"));
    expect(getUserMedia).toHaveBeenCalledWith({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: false,
      },
    });
    await waitFor(() =>
      expect(screen.getByTestId("translate-status")).toHaveTextContent("connecting"),
    );
  });

  it("mode buttons are disabled once a session is connecting", async () => {
    renderTranslatePage();
    await userEvent.click(screen.getByTestId("translate-toggle"));
    await waitFor(() => expect(screen.getByTestId("mode-one-way")).toBeDisabled());
    expect(screen.getByTestId("mode-two-way")).toBeDisabled();
  });

  it("switches transcript view modes", async () => {
    renderTranslatePage();
    await userEvent.click(screen.getByTestId("view-stacked"));
    expect(screen.getByTestId("view-stacked").className).toMatch(/on/);
    await userEvent.click(screen.getByTestId("view-columns"));
    expect(screen.getByTestId("view-columns").className).toMatch(/on/);
  });
});
