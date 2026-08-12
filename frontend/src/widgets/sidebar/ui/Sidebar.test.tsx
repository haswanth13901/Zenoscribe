import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthUser } from "@/features/auth/model/types";
import { Sidebar } from "@/widgets/sidebar/ui/Sidebar";

const regularUser: AuthUser = {
  id: "u1",
  username: "ada",
  full_name: "Ada Lovelace",
  role: "user",
};
const adminUser: AuthUser = {
  id: "u2",
  username: "grace",
  full_name: "Grace Hopper",
  role: "admin",
};

function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

function renderSidebar(user: AuthUser, currentPath = "/home") {
  return render(
    <MemoryRouter initialEntries={[currentPath]}>
      <Sidebar user={user} currentPath={currentPath} collapsed={false} />
      <LocationDisplay />
    </MemoryRouter>,
  );
}

describe("Sidebar", () => {
  let assignSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    assignSpy = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign: assignSpy, pathname: "/home" });
  });

  it("shows only Workspace links for a non-admin user", () => {
    renderSidebar(regularUser);
    expect(screen.getByText("Recorder")).toBeInTheDocument();
    expect(screen.getByText("Translate")).toBeInTheDocument();
    expect(screen.queryByText("Admin console")).not.toBeInTheDocument();
    expect(screen.queryByText("All Recordings")).not.toBeInTheDocument();
  });

  it("adds an Admin group for an admin user", () => {
    renderSidebar(adminUser);
    expect(screen.getByText("Admin console")).toBeInTheDocument();
    expect(screen.getByText("All Recordings")).toBeInTheDocument();
  });

  it("Home, Recorder, Translate and Admin console are real client-side <Link>s (in-SPA routes)", () => {
    renderSidebar(adminUser);
    const home = screen.getByRole("link", { name: "Home" });
    const recorder = screen.getByRole("link", { name: "Recorder" });
    const translate = screen.getByRole("link", { name: "Translate" });
    const adminConsole = screen.getByRole("link", { name: "Admin console" });
    expect(home).toHaveAttribute("href", "/home");
    expect(recorder).toHaveAttribute("href", "/app");
    expect(translate).toHaveAttribute("href", "/translate");
    expect(adminConsole).toHaveAttribute("href", "/admin");
  });

  it("clicking Recorder navigates client-side without touching window.location", async () => {
    renderSidebar(regularUser);
    await userEvent.click(screen.getByRole("link", { name: "Recorder" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/app");
    expect(assignSpy).not.toHaveBeenCalled();
  });

  it("clicking Translate navigates client-side without touching window.location", async () => {
    renderSidebar(regularUser);
    await userEvent.click(screen.getByRole("link", { name: "Translate" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/translate");
    expect(assignSpy).not.toHaveBeenCalled();
  });

  it("clicking Admin console navigates client-side without touching window.location", async () => {
    renderSidebar(adminUser);
    await userEvent.click(screen.getByRole("link", { name: "Admin console" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/admin");
    expect(assignSpy).not.toHaveBeenCalled();
  });

  it("highlights Admin console as active when already on /admin", () => {
    renderSidebar(adminUser, "/admin");
    expect(screen.getByRole("link", { name: "Admin console" }).className).toMatch(/active/);
  });

  it("All Recordings navigates client-side to /admin?tab=recordings, not a full reload", async () => {
    renderSidebar(adminUser);
    await userEvent.click(screen.getByText("All Recordings"));
    expect(screen.getByTestId("location")).toHaveTextContent("/admin?tab=recordings");
    expect(assignSpy).not.toHaveBeenCalled();
  });

  it("Upload/My recordings navigate client-side via ?upload=1/?recordings=1, not a full reload", async () => {
    renderSidebar(regularUser);

    await userEvent.click(screen.getByText("Upload"));
    expect(screen.getByTestId("location")).toHaveTextContent("/app?upload=1");

    await userEvent.click(screen.getByText("My recordings"));
    expect(screen.getByTestId("location")).toHaveTextContent("/app?recordings=1");

    expect(assignSpy).not.toHaveBeenCalled();
  });

  it("Upload opens in place when already on /admin, instead of defaulting to /app", async () => {
    renderSidebar(adminUser, "/admin");
    await userEvent.click(screen.getByText("Upload"));
    expect(screen.getByTestId("location")).toHaveTextContent("/admin?upload=1");
  });
});
