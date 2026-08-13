import type { ReactElement } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { AuthUser } from "@/features/auth/model/types";
import styles from "./Sidebar.module.css";

interface SidebarProps {
  user: AuthUser;
  currentPath: string;
  collapsed: boolean;
  // Set by AdminPage while its Recordings tab is showing, so All Recordings
  // can show as the active nav entry instead of Admin console (whose route
  // it's a tab within) staying highlighted underneath it.
  adminRecordingsTabActive?: boolean;
}

// All six post-login pages are now real client-side routes of this SPA, so
// their nav entries are genuine <Link>s (real anchors: middle-click/
// ctrl-click/open-in-new-tab work, unlike a button).
function SpaLink({
  label,
  to,
  active,
}: {
  label: string;
  to: string;
  active: boolean;
}): ReactElement {
  return (
    <Link to={to} className={active ? styles.active : undefined}>
      {label}
    </Link>
  );
}

// Port of sidebar.js's nav content as a props-driven component. The
// wrapping #appLayout/#appMainCol structure and collapse toggle live in
// AppLayout, since sidebar.js originally built both together.
export function Sidebar({
  user,
  currentPath,
  collapsed,
  adminRecordingsTabActive,
}: SidebarProps): ReactElement {
  const navigate = useNavigate();
  const path = currentPath.replace(/\/+$/, "") || "/";

  return (
    <nav id="appSidebar" className={`${styles.sidebar} ${collapsed ? styles.collapsed : ""}`}>
      <div className={styles.navGroup}>Workspace</div>
      <SpaLink label="Home" to="/home" active={path === "/home"} />
      <SpaLink label="Recorder" to="/app" active={path === "/app"} />
      <SpaLink label="Translate" to="/translate" active={path === "/translate"} />
      <SpaLink label="Upload" to="/upload" active={path === "/upload"} />
      <SpaLink label="My recordings" to="/recordings" active={path === "/recordings"} />
      {user.role === "admin" && (
        <>
          <div className={styles.navGroup}>Admin</div>
          <SpaLink
            label="Admin console"
            to="/admin?tab=users"
            active={path === "/admin" && !adminRecordingsTabActive}
          />
          <button
            type="button"
            className={adminRecordingsTabActive ? styles.active : undefined}
            onClick={() => navigate("/admin?tab=recordings")}
          >
            All Recordings
          </button>
        </>
      )}
    </nav>
  );
}
