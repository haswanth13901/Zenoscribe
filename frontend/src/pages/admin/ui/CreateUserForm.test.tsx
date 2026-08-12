import { configureStore } from "@reduxjs/toolkit";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Provider } from "react-redux";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { baseApi } from "@/shared/api/baseApi";
import authReducer, { setCredentials } from "@/features/auth/model/authSlice";
import type { AuthUser } from "@/features/auth/model/types";
import { server } from "@/mocks/server";
import { CreateUserForm } from "@/pages/admin/ui/CreateUserForm";

const admin: AuthUser = { id: "u1", username: "ada", full_name: "Ada Lovelace", role: "admin" };

function makeStore() {
  const store = configureStore({
    reducer: { auth: authReducer, [baseApi.reducerPath]: baseApi.reducer },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(baseApi.middleware),
  });
  store.dispatch(setCredentials({ token: "tok", user: admin }));
  return store;
}

function renderForm() {
  return render(
    <Provider store={makeStore()}>
      <CreateUserForm />
    </Provider>,
  );
}

async function fillForm() {
  await userEvent.type(screen.getByLabelText("Username"), "newbie");
  await userEvent.type(screen.getByLabelText("Full name"), "New Bie");
  await userEvent.type(screen.getByLabelText("Email"), "newbie@example.com");
  await userEvent.type(screen.getByLabelText(/Password/), "supersecret");
}

describe("CreateUserForm", () => {
  let alertSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    alertSpy = vi.fn();
    vi.stubGlobal("alert", alertSpy);
  });

  it("shows a success message and clears the text inputs, never calling window.alert", async () => {
    renderForm();
    await fillForm();
    await userEvent.click(screen.getByRole("button", { name: "Create user" }));

    await waitFor(() => expect(screen.getByText("Created newbie.")).toBeInTheDocument());
    expect(screen.getByLabelText("Username")).toHaveValue("");
    expect(screen.getByLabelText("Full name")).toHaveValue("");
    expect(screen.getByLabelText("Email")).toHaveValue("");
    expect(screen.getByLabelText(/Password/)).toHaveValue("");
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("trims username/full_name/email but not password before submitting", async () => {
    let sentBody: unknown;
    server.use(
      http.post("/api/admin/users", async ({ request }) => {
        sentBody = await request.json();
        return HttpResponse.json({ id: "x", username: "newbie", role: "user" });
      }),
    );
    renderForm();
    await userEvent.type(screen.getByLabelText("Username"), "  newbie  ");
    await userEvent.type(screen.getByLabelText("Password (min 8)"), "  supersecret  ");
    await userEvent.click(screen.getByRole("button", { name: "Create user" }));
    await waitFor(() => expect(sentBody).toBeDefined());
    expect(sentBody).toMatchObject({ username: "newbie", password: "  supersecret  " });
  });

  it("shows the server's 409 detail inline on a duplicate username", async () => {
    server.use(
      http.post("/api/admin/users", () =>
        HttpResponse.json({ detail: "Username already taken" }, { status: 409 }),
      ),
    );
    renderForm();
    await fillForm();
    await userEvent.click(screen.getByRole("button", { name: "Create user" }));
    await waitFor(() => expect(screen.getByText("Username already taken")).toBeInTheDocument());
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("shows the server's 400 detail inline for a short password", async () => {
    server.use(
      http.post("/api/admin/users", () =>
        HttpResponse.json(
          { detail: "Username required and password must be at least 8 characters" },
          { status: 400 },
        ),
      ),
    );
    renderForm();
    await fillForm();
    await userEvent.click(screen.getByRole("button", { name: "Create user" }));
    await waitFor(() => expect(screen.getByText(/at least 8 characters/)).toBeInTheDocument());
  });
});
