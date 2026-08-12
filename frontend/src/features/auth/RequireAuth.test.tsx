import { configureStore } from "@reduxjs/toolkit";
import { render, screen } from "@testing-library/react";
import { Provider } from "react-redux";
import { beforeEach, describe, expect, it, vi } from "vitest";
import authReducer, { setCredentials } from "./authSlice";
import { RequireAuth } from "./RequireAuth";
import type { AuthUser } from "./types";

const user: AuthUser = { id: "u1", username: "ada", full_name: "Ada Lovelace", role: "user" };

function renderWithStore(loggedIn: boolean) {
  const store = configureStore({ reducer: { auth: authReducer } });
  if (loggedIn) {
    store.dispatch(setCredentials({ token: "tok", user }));
  }
  return render(
    <Provider store={store}>
      <RequireAuth>
        <div>protected content</div>
      </RequireAuth>
    </Provider>,
  );
}

describe("RequireAuth", () => {
  let replaceSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    replaceSpy = vi.fn();
    vi.stubGlobal("location", { ...window.location, replace: replaceSpy });
  });

  it("renders children when a token and user are present", () => {
    renderWithStore(true);
    expect(screen.getByText("protected content")).toBeInTheDocument();
    expect(replaceSpy).not.toHaveBeenCalled();
  });

  it("redirects to /login and renders nothing when unauthenticated", () => {
    renderWithStore(false);
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    expect(replaceSpy).toHaveBeenCalledWith("/login");
  });
});
