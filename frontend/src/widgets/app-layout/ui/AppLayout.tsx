import { useState, type ReactElement, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import type { AuthUser } from "@/features/auth/model/types";
import { Header } from "@/widgets/header/ui/Header";
import { Sidebar } from "@/widgets/sidebar/ui/Sidebar";
import styles from "./AppLayout.module.css";

interface AppLayoutProps {
  user: AuthUser;
  children: ReactNode;
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

// Reproduces the #appLayout/#appMainCol structure sidebar.js builds by DOM
// injection: header full-width above, sidebar + main content side by side
// below, with a collapse toggle absolutely positioned so it stays put and
// clickable even when the sidebar collapses to zero width.
export function AppLayout({ user, children }: AppLayoutProps): ReactElement {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();

  return (
    <>
      <Header user={user} />
      <div id="appLayout" className={styles.layout}>
        <Sidebar user={user} currentPath={location.pathname} collapsed={collapsed} />
        <div id="appMainCol" className={styles.mainCol}>
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
