import { configureStore } from "@reduxjs/toolkit";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Provider } from "react-redux";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { baseApi } from "@/shared/api/baseApi";
import authReducer, { setCredentials } from "@/features/auth/model/authSlice";
import type { AuthUser } from "@/features/auth/model/types";
import { sampleRecordings } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { HomePage } from "@/pages/home/ui/HomePage";

const user: AuthUser = { id: "u1", username: "ada", full_name: "Ada Lovelace", role: "user" };

function makeStore() {
  const store = configureStore({
    reducer: { auth: authReducer, [baseApi.reducerPath]: baseApi.reducer },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(baseApi.middleware),
  });
  store.dispatch(setCredentials({ token: "tok", user }));
  return store;
}

function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

function renderHomePage() {
  return render(
    <Provider store={makeStore()}>
      <MemoryRouter initialEntries={["/home"]}>
        <HomePage />
        <LocationDisplay />
      </MemoryRouter>
    </Provider>,
  );
}

describe("HomePage", () => {
  it("shows a loading state, then the greeting and recent session data", async () => {
    renderHomePage();

    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(screen.getByText(/Good (morning|afternoon|evening), Ada Lovelace/)).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
  });

  it("renders action buttons and view-all as buttons (client-side navigate), not anchors", async () => {
    renderHomePage();
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());

    // The Sidebar (rendered here via AppLayout) now contains real <Link>s
    // for Home/Recorder - those are expected. What this test guards is that
    // the page's own action triggers stay <button>s, not anchors, even
    // though "Start recording" now navigates to /app client-side too.
    expect(screen.getByTestId("go-record").tagName).toBe("BUTTON");
    expect(screen.getByTestId("go-translate").tagName).toBe("BUTTON");
    expect(screen.getByText("View all").tagName).toBe("BUTTON");
  });

  it("Start recording navigates client-side to /app", async () => {
    renderHomePage();
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
    await userEvent.click(screen.getByTestId("go-record"));
    expect(screen.getByTestId("location")).toHaveTextContent("/app");
  });

  it("shows an error state and recovers via retry", async () => {
    server.use(http.get("/api/recordings", () => HttpResponse.error()));
    renderHomePage();

    await waitFor(() => expect(screen.getByText(/couldn't load/i)).toBeInTheDocument());
    expect(screen.getAllByText("—")).toHaveLength(2); // MonthlyStats placeholder

    server.resetHandlers(); // subsequent request (the retry) hits the real handler again
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));

    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
  });
});
