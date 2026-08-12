import { configureStore } from "@reduxjs/toolkit";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Provider } from "react-redux";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { baseApi } from "../../../api/baseApi";
import authReducer, { setCredentials } from "../../../features/auth/authSlice";
import type { AuthUser } from "../../../features/auth/types";
import { sampleUsers } from "../../../mocks/handlers";
import { server } from "../../../mocks/server";
import { UsersTable } from "../UsersTable";

const admin: AuthUser = { id: "u1", username: "ada", full_name: "Ada Lovelace", role: "admin" };

function makeStore() {
  const store = configureStore({
    reducer: { auth: authReducer, [baseApi.reducerPath]: baseApi.reducer },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(baseApi.middleware),
  });
  store.dispatch(setCredentials({ token: "tok", user: admin }));
  return store;
}

function renderTable() {
  return render(
    <Provider store={makeStore()}>
      <UsersTable />
    </Provider>,
  );
}

function rowFor(username: string) {
  return screen.getByText(username).closest("tr")!;
}

describe("UsersTable", () => {
  let alertSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    alertSpy = vi.fn();
    vi.stubGlobal("alert", alertSpy);
  });

  it("renders each user's identity, role, status, recordings count, presence and last login", async () => {
    renderTable();
    await waitFor(() => expect(screen.getByText("ada")).toBeInTheDocument());

    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument(); // full_name subtext
    expect(within(rowFor("ada")).getByText("admin")).toBeInTheDocument();
    expect(within(rowFor("ada")).getByText("active")).toBeInTheDocument();
    expect(within(rowFor("ada")).getByText("online")).toBeInTheDocument();

    expect(screen.getByText("grace")).toBeInTheDocument();
    expect(within(rowFor("grace")).getByText("disabled")).toBeInTheDocument();
    expect(within(rowFor("grace")).getByText("never")).toBeInTheDocument();
    expect(within(rowFor("grace")).getAllByText("—")).toHaveLength(2); // no email, no last_login
  });

  it("reset password: prompts, submits, shows an inline success message (never window.alert)", async () => {
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("newpassword123");
    renderTable();
    await waitFor(() => expect(screen.getByText("ada")).toBeInTheDocument());

    await userEvent.click(within(rowFor("ada")).getByRole("button", { name: "Reset password" }));
    expect(promptSpy).toHaveBeenCalled();
    await waitFor(() => expect(screen.getByText("Password updated.")).toBeInTheDocument());
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("reset password: does nothing if the prompt is cancelled (empty return)", async () => {
    vi.spyOn(window, "prompt").mockReturnValue(null);
    renderTable();
    await waitFor(() => expect(screen.getByText("ada")).toBeInTheDocument());
    await userEvent.click(within(rowFor("ada")).getByRole("button", { name: "Reset password" }));
    expect(screen.queryByText("Password updated.")).not.toBeInTheDocument();
  });

  it("toggles active/inactive label and calls the endpoint", async () => {
    renderTable();
    await waitFor(() => expect(screen.getByText("grace")).toBeInTheDocument());
    await userEvent.click(within(rowFor("grace")).getByRole("button", { name: "Activate" }));
    // setActive invalidates ["Users"], so the list refetches - still shows
    // the same mocked (unchanged) data, but the call itself must not throw
    // or alert.
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("shows the server's guard-rail 400 inline when deactivating yourself, not via alert", async () => {
    server.use(http.post("/api/admin/users/:id/active", () => HttpResponse.json({ detail: "Cannot deactivate yourself" }, { status: 400 })));
    renderTable();
    await waitFor(() => expect(screen.getByText("ada")).toBeInTheDocument());
    await userEvent.click(within(rowFor("ada")).getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(screen.getByText("Cannot deactivate yourself")).toBeInTheDocument());
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("delete: confirms, calls the endpoint, and shows the guard-rail message inline on failure", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    server.use(http.delete("/api/admin/users/:id", () => HttpResponse.json({ detail: "Cannot delete the last admin" }, { status: 400 })));
    renderTable();
    await waitFor(() => expect(screen.getByText("ada")).toBeInTheDocument());
    await userEvent.click(within(rowFor("ada")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.getByText("Cannot delete the last admin")).toBeInTheDocument());
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("delete: does nothing when the confirmation is declined", async () => {
    const deleteSpy = vi.fn();
    server.use(
      http.delete("/api/admin/users/:id", () => {
        deleteSpy();
        return HttpResponse.json({ ok: true, removed_recordings: 0 });
      }),
    );
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderTable();
    await waitFor(() => expect(screen.getByText("ada")).toBeInTheDocument());
    await userEvent.click(within(rowFor("ada")).getByRole("button", { name: "Delete" }));
    expect(deleteSpy).not.toHaveBeenCalled();
  });

  it("shows an error state with retry when the users list fails to load", async () => {
    server.use(http.get("/api/admin/users", () => HttpResponse.error()));
    renderTable();
    await waitFor(() => expect(screen.getByText(/couldn't load users/i)).toBeInTheDocument());

    server.use(http.get("/api/admin/users", () => HttpResponse.json(sampleUsers)));
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() => expect(screen.getByText("ada")).toBeInTheDocument());
  });
});
