import { useEffect, useState, type ReactElement, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import type { AuthUser } from "@/features/auth/model/types";
import { Header } from "@/widgets/header/ui/Header";
import { Sidebar } from "@/widgets/sidebar/ui/Sidebar";
import styles from "./AppLayout.module.css";

interface AppLayoutProps {
  user: AuthUser;
  children: ReactNode;
  // Forwarded to Sidebar so it can show All Recordings as active instead of
  // Admin console while AdminPage's Recordings tab is showing.
  adminRecordingsTabActive?: boolean;
}

const ICON_PANEL = (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <line x1="9" y1="3" x2="9" y2="21" />
  </svg>
);

const NARROW_QUERY = "(max-width: 720px)";

// matchMedia isn't implemented in jsdom (the test environment) and is
// absent on some very old browsers - treat "can't tell" as "not narrow"
// rather than throwing, so this degrades to the pre-existing
// always-expanded behavior instead of crashing the page.
function isNarrowViewport(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(NARROW_QUERY).matches;
}

// Reproduces the #appLayout/#appMainCol structure sidebar.js builds by DOM
// injection: header full-width above, sidebar + main content side by side
// below, with a collapse toggle absolutely positioned so it stays put and
// clickable even when the sidebar collapses to zero width.
//
// Below NARROW_QUERY, Sidebar.module.css switches the sidebar from a
// flex column (pushes content) to an absolutely positioned overlay drawer
// (floats over content) - so it starts collapsed on phones/narrow tablets
// instead of eating most of the viewport width by default, and a tap
// outside it (the backdrop) or a nav click closes it again.
export function AppLayout({
  user,
  children,
  adminRecordingsTabActive,
}: AppLayoutProps): ReactElement {
  const [collapsed, setCollapsed] = useState(isNarrowViewport);
  const location = useLocation();

  // Auto-close the drawer after an in-app navigation on narrow viewports -
  // on wide viewports the sidebar isn't a drawer, so this is a no-op there.
  useEffect(() => {
    if (isNarrowViewport()) setCollapsed(true);
  }, [location.pathname]);

  return (
    <>
      <Header user={user} />
      <div id="appLayout" className={styles.layout}>
        <Sidebar
          user={user}
          currentPath={location.pathname}
          collapsed={collapsed}
          adminRecordingsTabActive={adminRecordingsTabActive}
        />
        {!collapsed && (
          <div className={styles.backdrop} onClick={() => setCollapsed(true)} aria-hidden="true" />
        )}
        <div
          id="appMainCol"
          className={`${styles.mainCol} ${collapsed ? styles.mainColCollapsed : ""}`}
        >
          {children}
        </div>
        <button
          type="button"
          className={styles.sidebarToggle}
          title="Toggle sidebar"
          onClick={() => setCollapsed((c) => !c)}
        >
          {ICON_PANEL}
        </button>
      </div>
    </>
  );
}
