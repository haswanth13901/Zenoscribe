import { configureStore } from "@reduxjs/toolkit";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { beforeEach, describe, expect, it, vi } from "vitest";
import authReducer from "@/features/auth/model/authSlice";
import type { AuthUser } from "@/features/auth/model/types";
import { Header } from "@/widgets/header/ui/Header";

const user: AuthUser = {
  id: "u1",
  username: "ada.lovelace",
  full_name: "Ada Lovelace",
  role: "user",
};

function renderHeader() {
  const store = configureStore({ reducer: { auth: authReducer } });
  return render(
    <Provider store={store}>
      <Header user={user} />
    </Provider>,
  );
}

describe("Header", () => {
  let assignSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    assignSpy = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign: assignSpy, href: "" });
  });

  it("shows the username and its initials avatar", () => {
    renderHeader();
    expect(screen.getByText("ada.lovelace")).toBeInTheDocument();
    expect(screen.getByText("AL")).toBeInTheDocument();
  });

  it("navigates to /home when the brand is clicked", async () => {
    renderHeader();
    await userEvent.click(screen.getByTitle("Home"));
    expect(assignSpy).toHaveBeenCalledWith("/home");
  });

  it("opens the account menu and signs out, clearing sessionStorage", async () => {
    sessionStorage.setItem("token", "tok");
    sessionStorage.setItem("user", JSON.stringify(user));
    renderHeader();

    await userEvent.click(screen.getByText("ada.lovelace"));
    const signOutBtn = await screen.findByRole("button", { name: /sign out/i });
    await userEvent.click(signOutBtn);

    expect(sessionStorage.getItem("token")).toBeNull();
    expect(window.location.href).toBe("/login");
  });
});
