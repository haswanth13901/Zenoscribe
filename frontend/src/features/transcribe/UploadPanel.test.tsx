import { configureStore } from "@reduxjs/toolkit";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Provider } from "react-redux";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { baseApi } from "../../api/baseApi";
import authReducer, { setCredentials } from "../auth/authSlice";
import type { AuthUser } from "../auth/types";
import { server } from "../../mocks/server";
import { UploadPanel } from "./UploadPanel";

const user: AuthUser = { id: "u1", username: "ada", full_name: "Ada Lovelace", role: "user" };

function makeStore() {
  const store = configureStore({
    reducer: { auth: authReducer, [baseApi.reducerPath]: baseApi.reducer },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(baseApi.middleware),
  });
  store.dispatch(setCredentials({ token: "tok", user }));
  return store;
}

function renderPanel(open = true) {
  return render(
    <Provider store={makeStore()}>
      <UploadPanel open={open} onClose={vi.fn()} />
    </Provider>,
  );
}

async function pickFile() {
  const file = new File(["audio-bytes"], "session.wav", { type: "audio/wav" });
  const input = screen.getByTestId("upload-file-input");
  await userEvent.upload(input, file);
}

describe("UploadPanel", () => {
  let alertSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    alertSpy = vi.fn();
    vi.stubGlobal("alert", alertSpy);
  });

  it("renders nothing when closed", () => {
    const { container } = renderPanel(false);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the selected filename after choosing a file", async () => {
    renderPanel();
    await pickFile();
    expect(screen.getByText(/Selected: session\.wav/)).toBeInTheDocument();
  });

  it("populates the language select from the API, defaulting to English", async () => {
    renderPanel();
    await waitFor(() => expect(screen.getByRole("option", { name: "Spanish" })).toBeInTheDocument());
    expect(screen.getByLabelText(/target language/i)).toHaveValue("en");
  });

  it("falls back to English-only when the languages request fails", async () => {
    server.use(http.get("/api/languages", () => HttpResponse.error()));
    renderPanel();
    await waitFor(() => expect(screen.getByRole("option", { name: "English" })).toBeInTheDocument());
    expect(screen.queryByRole("option", { name: "Spanish" })).not.toBeInTheDocument();
  });

  it("disables Transcribe until a file is chosen", () => {
    renderPanel();
    expect(screen.getByRole("button", { name: "Transcribe" })).toBeDisabled();
  });

  it("transcribes without a target_language and shows the result, never calling window.alert", async () => {
    let sawTargetLanguage: string | null = "not-checked";
    server.use(
      http.post("/api/transcribe/translate", ({ request }) => {
        sawTargetLanguage = new URL(request.url).searchParams.get("target_language");
        return HttpResponse.json({ turns: [{ text: "hello world" }] });
      }),
    );
    renderPanel();
    await pickFile();
    await userEvent.click(screen.getByRole("button", { name: "Transcribe" }));
    await waitFor(() => expect(screen.getByText("hello world")).toBeInTheDocument());
    expect(sawTargetLanguage).toBeNull();
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("sends the FormData body with the browser-set multipart Content-Type", async () => {
    let contentType: string | null = null;
    server.use(
      http.post("/api/transcribe/translate", ({ request }) => {
        contentType = request.headers.get("Content-Type");
        return HttpResponse.json({ turns: [{ text: "ok" }] });
      }),
    );
    renderPanel();
    await pickFile();
    await userEvent.click(screen.getByRole("button", { name: "Transcribe" }));
    await waitFor(() => expect(screen.getByText("ok")).toBeInTheDocument());
    expect(contentType).toMatch(/^multipart\/form-data/);
  });

  it("shows an inline error (not an alert) on a network-level failure", async () => {
    server.use(http.post("/api/transcribe/translate", () => HttpResponse.error()));
    renderPanel();
    await pickFile();
    await userEvent.click(screen.getByRole("button", { name: "Transcribe" }));
    await waitFor(() => expect(screen.getByText(/transcription failed/i)).toBeInTheDocument());
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("includes the server's status and detail in the inline error, like the original alert() did", async () => {
    server.use(
      http.post("/api/transcribe/translate", () => HttpResponse.json({ detail: "Transcription timed out: boom" }, { status: 504 })),
    );
    renderPanel();
    await pickFile();
    await userEvent.click(screen.getByRole("button", { name: "Transcribe" }));
    await waitFor(() => expect(screen.getByText(/504/)).toBeInTheDocument());
    expect(screen.getByText(/timed out/i)).toBeInTheDocument();
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("transcribe-and-translate passes the selected target language", async () => {
    let sawTargetLanguage: string | null = null;
    server.use(
      http.post("/api/transcribe/translate", ({ request }) => {
        sawTargetLanguage = new URL(request.url).searchParams.get("target_language");
        return HttpResponse.json({ turns: [{ text: "hola mundo" }] });
      }),
    );
    renderPanel();
    await pickFile();
    await waitFor(() => expect(screen.getByRole("option", { name: "Spanish" })).toBeInTheDocument());
    await userEvent.selectOptions(screen.getByLabelText(/target language/i), "es");
    await userEvent.click(screen.getByRole("button", { name: "Transcribe & Translate" }));
    await waitFor(() => expect(screen.getByText("hola mundo")).toBeInTheDocument());
    expect(sawTargetLanguage).toBe("es");
  });
});
