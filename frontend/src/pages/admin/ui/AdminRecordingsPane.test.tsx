import { configureStore } from "@reduxjs/toolkit";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Provider } from "react-redux";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { baseApi } from "@/shared/api/baseApi";
import authReducer, { setCredentials } from "@/features/auth/model/authSlice";
import type { AuthUser } from "@/features/auth/model/types";
import { sampleRecordings, sampleUsers } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { AdminRecordingsPane } from "@/pages/admin/ui/AdminRecordingsPane";

const admin: AuthUser = { id: "u1", username: "ada", full_name: "Ada Lovelace", role: "admin" };

function makeStore() {
  const store = configureStore({
    reducer: { auth: authReducer, [baseApi.reducerPath]: baseApi.reducer },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(baseApi.middleware),
  });
  store.dispatch(setCredentials({ token: "tok", user: admin }));
  return store;
}

function renderPane() {
  return render(
    <Provider store={makeStore()}>
      <AdminRecordingsPane />
    </Provider>,
  );
}

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:mock-url");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});

describe("AdminRecordingsPane", () => {
  it("populates the user filter from the users list and renders recordings", async () => {
    renderPane();
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
    expect(screen.getByRole("option", { name: sampleUsers[0].username })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "All users" })).toBeInTheDocument();
  });

  it("shows an empty state when there are no recordings", async () => {
    server.use(http.get("/api/recordings", () => HttpResponse.json([])));
    renderPane();
    await waitFor(() => expect(screen.getByText("No recordings yet.")).toBeInTheDocument());
  });

  it("shows an error state with retry", async () => {
    server.use(http.get("/api/recordings", () => HttpResponse.error()));
    renderPane();
    await waitFor(() => expect(screen.getByText(/couldn't load recordings/i)).toBeInTheDocument());

    server.use(http.get("/api/recordings", () => HttpResponse.json(sampleRecordings)));
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
  });

  it("downloads the transcript for a row", async () => {
    renderPane();
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Transcript" }));
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled());
  });

  it("deletes a recording after confirmation", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPane();
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());

    server.use(http.get("/api/recordings", () => HttpResponse.json([])));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.getByText("No recordings yet.")).toBeInTheDocument());
  });
});
