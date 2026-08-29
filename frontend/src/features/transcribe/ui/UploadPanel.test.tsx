import { configureStore } from "@reduxjs/toolkit";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { Provider } from "react-redux";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { baseApi } from "@/shared/api/baseApi";
import authReducer, { setCredentials } from "@/features/auth/model/authSlice";
import type { AuthUser } from "@/features/auth/model/types";
import { server } from "@/mocks/server";
import { UploadPanel } from "@/features/transcribe/ui/UploadPanel";

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
      <UploadPanel open={open} />
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
    await waitFor(() =>
      expect(screen.getByRole("option", { name: "Spanish" })).toBeInTheDocument(),
    );
    expect(screen.getByLabelText(/target language/i)).toHaveValue("en");
  });

  it("falls back to English-only when the languages request fails", async () => {
    server.use(http.get("/api/languages", () => HttpResponse.error()));
    renderPanel();
    await waitFor(() =>
      expect(screen.getByRole("option", { name: "English" })).toBeInTheDocument(),
    );
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

  it("Reset clears the selected file and the transcription result", async () => {
    server.use(
      http.post("/api/transcribe/translate", () =>
        HttpResponse.json({ turns: [{ text: "hello world" }] }),
      ),
    );
    renderPanel();
    await pickFile();
    await userEvent.click(screen.getByRole("button", { name: "Transcribe" }));
    await waitFor(() => expect(screen.getByText("hello world")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Reset" }));

    expect(screen.queryByText(/Selected: session\.wav/)).not.toBeInTheDocument();
    expect(screen.queryByText("hello world")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transcribe" })).toBeDisabled();
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
      http.post("/api/transcribe/translate", () =>
        HttpResponse.json({ detail: "Transcription timed out: boom" }, { status: 504 }),
      ),
    );
    renderPanel();
    await pickFile();
    await userEvent.click(screen.getByRole("button", { name: "Transcribe" }));
    await waitFor(() => expect(screen.getByText(/504/)).toBeInTheDocument());
    expect(screen.getByText(/timed out/i)).toBeInTheDocument();
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("Transcribe & Translate replaces the previous transcription rather than stacking under it", async () => {
    let call = 0;
    server.use(
      http.post("/api/transcribe/translate", () => {
        call += 1;
        return HttpResponse.json({
          turns: [{ text: call === 1 ? "plain transcription" : "translated text" }],
        });
      }),
    );
    renderPanel();
    await pickFile();

    await userEvent.click(screen.getByRole("button", { name: "Transcribe" }));
    await waitFor(() => expect(screen.getByText("plain transcription")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Transcribe & Translate" }));
    await waitFor(() => expect(screen.getByText("translated text")).toBeInTheDocument());
    expect(screen.queryByText("plain transcription")).not.toBeInTheDocument();
  });

  it("Transcribe replaces a previous translation too - only ever one result on screen", async () => {
    let call = 0;
    server.use(
      http.post("/api/transcribe/translate", () => {
        call += 1;
        return HttpResponse.json({
          turns: [{ text: call === 1 ? "translated text" : "plain transcription" }],
        });
      }),
    );
    renderPanel();
    await pickFile();

    await userEvent.click(screen.getByRole("button", { name: "Transcribe & Translate" }));
    await waitFor(() => expect(screen.getByText("translated text")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Transcribe" }));
    await waitFor(() => expect(screen.getByText("plain transcription")).toBeInTheDocument());
    expect(screen.queryByText("translated text")).not.toBeInTheDocument();
  });

  it("clears the other action's stale error, not just its result", async () => {
    let call = 0;
    server.use(
      http.post("/api/transcribe/translate", () => {
        call += 1;
        return call === 1
          ? HttpResponse.json({ detail: "upstream exploded" }, { status: 502 })
          : HttpResponse.json({ turns: [{ text: "translated text" }] });
      }),
    );
    renderPanel();
    await pickFile();

    await userEvent.click(screen.getByRole("button", { name: "Transcribe" }));
    await waitFor(() => expect(screen.getByTestId("upload-transcribe-error")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Transcribe & Translate" }));
    await waitFor(() => expect(screen.getByText("translated text")).toBeInTheDocument());
    expect(screen.queryByTestId("upload-transcribe-error")).not.toBeInTheDocument();
  });

  it("shows elapsed time and keep-the-tab-open copy while a transcription is in flight", async () => {
    server.use(
      http.post("/api/transcribe/translate", async () => {
        await delay(200);
        return HttpResponse.json({ turns: [{ text: "done" }] });
      }),
    );
    renderPanel();
    await pickFile();
    await userEvent.click(screen.getByRole("button", { name: "Transcribe" }));

    // The 60s edge timeout this UI was added alongside made a long upload
    // look like a failure; the point of the banner is that a slow request is
    // visibly still running, and that closing the tab has a cost.
    const progress = await screen.findByTestId("upload-progress");
    expect(progress).toHaveTextContent(/Transcribing - \d\d:\d\d/);
    expect(progress).toHaveTextContent(/keep this tab open/i);

    await waitFor(() => expect(screen.getByText("done")).toBeInTheDocument());
    expect(screen.queryByTestId("upload-progress")).not.toBeInTheDocument();
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
    await waitFor(() =>
      expect(screen.getByRole("option", { name: "Spanish" })).toBeInTheDocument(),
    );
    await userEvent.selectOptions(screen.getByLabelText(/target language/i), "es");
    await userEvent.click(screen.getByRole("button", { name: "Transcribe & Translate" }));
    await waitFor(() => expect(screen.getByText("hola mundo")).toBeInTheDocument());
    expect(sawTargetLanguage).toBe("es");
  });
});
