import { configureStore } from "@reduxjs/toolkit";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { baseApi } from "@/shared/api/baseApi";
import authReducer, { setCredentials } from "@/features/auth/model/authSlice";
import type { AuthUser } from "@/features/auth/model/types";
import { sampleRecordings, sampleUsers } from "@/mocks/handlers";
import { AdminPage } from "@/pages/admin/ui/AdminPage";

const admin: AuthUser = { id: "u1", username: "ada", full_name: "Ada Lovelace", role: "admin" };

function makeStore() {
  const store = configureStore({
    reducer: { auth: authReducer, [baseApi.reducerPath]: baseApi.reducer },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(baseApi.middleware),
  });
  store.dispatch(setCredentials({ token: "tok", user: admin }));
  return store;
}

function renderAdminPage(initialPath = "/admin") {
  return render(
    <Provider store={makeStore()}>
      <MemoryRouter initialEntries={[initialPath]}>
        <AdminPage />
      </MemoryRouter>
    </Provider>,
  );
}

describe("AdminPage", () => {
  it("defaults to the Users tab", async () => {
    renderAdminPage();
    await waitFor(() => expect(screen.getByText(sampleUsers[0].username)).toBeInTheDocument());
    expect(screen.getByText("Register a user")).toBeInTheDocument();
  });

  it("switches to the Recordings tab on click", async () => {
    renderAdminPage();
    await waitFor(() => expect(screen.getByText(sampleUsers[0].username)).toBeInTheDocument());
    // Not `getByRole("button", { name: "All Recordings" })` - the sidebar
    // also has an "All Recordings" button (its admin-group deep-link).
    await userEvent.click(screen.getByTestId("tab-recordings"));
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
    expect(screen.queryByText("Register a user")).not.toBeInTheDocument();
  });

  it("opens directly on the Recordings tab via the ?tab=recordings deep-link", async () => {
    renderAdminPage("/admin?tab=recordings");
    await waitFor(() => expect(screen.getByText(sampleRecordings[0].preview)).toBeInTheDocument());
    expect(screen.queryByText("Register a user")).not.toBeInTheDocument();
  });

  it("opens the upload panel via the ?upload=1 deep-link", async () => {
    renderAdminPage("/admin?upload=1");
    await waitFor(() => expect(screen.getByText("Transcribe a file")).toBeInTheDocument());
  });
});
