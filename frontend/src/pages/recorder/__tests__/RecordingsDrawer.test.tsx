import { configureStore } from "@reduxjs/toolkit";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Provider } from "react-redux";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { baseApi } from "../../../api/baseApi";
import authReducer, { setCredentials } from "../../../features/auth/authSlice";
import type { AuthUser } from "../../../features/auth/types";
import { sampleRecordings } from "../../../mocks/handlers";
import { server } from "../../../mocks/server";
import { RecordingsDrawer } from "../RecordingsDrawer";

const user: AuthUser = { id: "u1", username: "ada", full_name: "Ada Lovelace", role: "user" };

function makeStore() {
  const store = configureStore({
    reducer: { auth: authReducer, [baseApi.reducerPath]: baseApi.reducer },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(baseApi.middleware),
  });
  store.dispatch(setCredentials({ token: "tok", user }));
  return store;
}

function renderDrawer(open = true) {
  return render(
    <Provider store={makeStore()}>
      <RecordingsDrawer open={open} onClose={vi.fn()} />
    </Provider>,
  );
}

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:mock-url");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("RecordingsDrawer", () => {
  it("renders nothing when closed", () => {
    const { container } = renderDrawer(false);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows loading, then the recordings list", async () => {
    renderDrawer();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
  });

  it("shows an empty state when there are no recordings", async () => {
    server.use(http.get("/api/recordings", () => HttpResponse.json([])));
    renderDrawer();
    await waitFor(() => expect(screen.getByText("No recordings yet.")).toBeInTheDocument());
  });

  it("shows a distinct error state with a working retry", async () => {
    server.use(http.get("/api/recordings", () => HttpResponse.error()));
    renderDrawer();
    await waitFor(() => expect(screen.getByText(/couldn't load/i)).toBeInTheDocument());

    server.use(http.get("/api/recordings", () => HttpResponse.json(sampleRecordings)));
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
  });

  it("downloads the transcript as a text blob", async () => {
    renderDrawer();
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Transcript" }));
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled());
  });

  it("downloads the audio file with an authenticated fetch", async () => {
    renderDrawer();
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Audio" }));
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled());
  });

  it("deletes a recording after confirmation, refreshing the list", async () => {
    renderDrawer();
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());

    server.use(http.get("/api/recordings", () => HttpResponse.json([])));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => expect(screen.getByText("No recordings yet.")).toBeInTheDocument());
  });

  it("does not delete when the confirmation is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    renderDrawer();
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument();
  });
});
