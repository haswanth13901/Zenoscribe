import { configureStore } from "@reduxjs/toolkit";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { baseApi } from "@/shared/api/baseApi";
import authReducer, { setCredentials } from "@/features/auth/model/authSlice";
import type { AuthUser } from "@/features/auth/model/types";
import { sampleRecordings } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { MyRecordingsPage } from "@/pages/recordings/ui/MyRecordingsPage";

const user: AuthUser = { id: "u1", username: "ada", full_name: "Ada Lovelace", role: "user" };

function makeStore() {
  const store = configureStore({
    reducer: { auth: authReducer, [baseApi.reducerPath]: baseApi.reducer },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(baseApi.middleware),
  });
  store.dispatch(setCredentials({ token: "tok", user }));
  return store;
}

function renderPage() {
  return render(
    <Provider store={makeStore()}>
      <MemoryRouter initialEntries={["/recordings"]}>
        <MyRecordingsPage />
      </MemoryRouter>
    </Provider>,
  );
}

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:mock-url");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});

describe("MyRecordingsPage", () => {
  it("shows loading, then the recordings table", async () => {
    renderPage();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
  });

  it("shows an empty state when there are no recordings", async () => {
    server.use(http.get("/api/recordings", () => HttpResponse.json([])));
    renderPage();
    await waitFor(() => expect(screen.getByText("No recordings yet.")).toBeInTheDocument());
  });

  it("shows a distinct error state with a working retry", async () => {
    server.use(http.get("/api/recordings", () => HttpResponse.error()));
    renderPage();
    await waitFor(() => expect(screen.getByText(/couldn't load/i)).toBeInTheDocument());

    server.use(http.get("/api/recordings", () => HttpResponse.json(sampleRecordings)));
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
  });

  it("downloads the transcript as a text blob", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Transcript" }));
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled());
  });

  it("downloads the audio file with an authenticated fetch", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Audio" }));
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled());
  });

  it("does not render a Delete button", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("clears date filters via the Clear button", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
    const from = screen.getByLabelText("From") as HTMLInputElement;
    await userEvent.type(from, "2026-01-01");
    expect(from.value).toBe("2026-01-01");
    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(from.value).toBe("");
  });
});
