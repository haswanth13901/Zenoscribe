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

  it("Home, Recorder, Translate, Upload, My recordings and Admin console are real client-side <Link>s (in-SPA routes)", () => {
    renderSidebar(adminUser);
    const home = screen.getByRole("link", { name: "Home" });
    const recorder = screen.getByRole("link", { name: "Recorder" });
    const translate = screen.getByRole("link", { name: "Translate" });
    const upload = screen.getByRole("link", { name: "Upload" });
    const myRecordings = screen.getByRole("link", { name: "My recordings" });
    const adminConsole = screen.getByRole("link", { name: "Admin console" });
    expect(home).toHaveAttribute("href", "/home");
    expect(recorder).toHaveAttribute("href", "/app");
    expect(translate).toHaveAttribute("href", "/translate");
    expect(upload).toHaveAttribute("href", "/upload");
    expect(myRecordings).toHaveAttribute("href", "/recordings");
    expect(adminConsole).toHaveAttribute("href", "/admin?tab=users");
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

  it("clicking Admin console navigates client-side to /admin?tab=users, not a full reload", async () => {
    renderSidebar(adminUser);
    await userEvent.click(screen.getByRole("link", { name: "Admin console" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/admin?tab=users");
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

  it("clicking Upload navigates client-side to /upload without touching window.location", async () => {
    renderSidebar(regularUser);
    await userEvent.click(screen.getByRole("link", { name: "Upload" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/upload");
    expect(assignSpy).not.toHaveBeenCalled();
  });

  it("clicking My recordings navigates client-side to /recordings without touching window.location", async () => {
    renderSidebar(regularUser);
    await userEvent.click(screen.getByRole("link", { name: "My recordings" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/recordings");
    expect(assignSpy).not.toHaveBeenCalled();
  });

  it("highlights Upload as active when already on /upload", () => {
    renderSidebar(regularUser, "/upload");
    expect(screen.getByRole("link", { name: "Upload" }).className).toMatch(/active/);
    expect(screen.getByRole("link", { name: "Recorder" }).className).not.toMatch(/active/);
  });

  it("highlights My recordings as active when already on /recordings", () => {
    renderSidebar(regularUser, "/recordings");
    expect(screen.getByRole("link", { name: "My recordings" }).className).toMatch(/active/);
    expect(screen.getByRole("link", { name: "Recorder" }).className).not.toMatch(/active/);
  });

  it("highlights All Recordings, not Admin console, while AdminPage's Recordings tab is showing", () => {
    render(
      <MemoryRouter initialEntries={["/admin"]}>
        <Sidebar user={adminUser} currentPath="/admin" collapsed={false} adminRecordingsTabActive />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Admin console" }).className).not.toMatch(/active/);
    expect(screen.getByText("All Recordings").className).toMatch(/active/);
  });

  it("highlights Admin console, not All Recordings, when the Recordings tab isn't active", () => {
    renderSidebar(adminUser, "/admin");
    expect(screen.getByRole("link", { name: "Admin console" }).className).toMatch(/active/);
    expect(screen.getByText("All Recordings").className).toBeFalsy();
  });
});
