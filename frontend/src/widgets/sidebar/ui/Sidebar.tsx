import type { ReactElement } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { AuthUser } from "@/features/auth/model/types";
import styles from "./Sidebar.module.css";

interface SidebarProps {
  user: AuthUser;
  currentPath: string;
  collapsed: boolean;
}

// All four post-login pages are now real client-side routes of this SPA,
// so their nav entries are genuine <Link>s (real anchors: middle-click/
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
export function Sidebar({ user, currentPath, collapsed }: SidebarProps): ReactElement {
  const navigate = useNavigate();
  const path = currentPath.replace(/\/+$/, "") || "/";

  // Upload/My recordings/All Recordings are transient panel/tab triggers,
  // not pages, so they stay buttons - but navigate client-side (via the
  // same ?upload=1/?recordings=1/?tab=recordings query-param signal
  // RecorderPage/AdminPage read and clear) instead of a full reload, so
  // triggering them while already on the target page doesn't reload the
  // whole SPA.
  //
  // Upload's target is page-aware: only /app and /admin ever host their own
  // upload panel (home.html/translate.html never had a #uploadBtn either),
  // so open it in place when already on one of those, else default to /app.
  const uploadTarget = path === "/app" || path === "/admin" ? `${path}?upload=1` : "/app?upload=1";

  return (
    <nav id="appSidebar" className={`${styles.sidebar} ${collapsed ? styles.collapsed : ""}`}>
      <div className={styles.navGroup}>Workspace</div>
      <SpaLink label="Home" to="/home" active={path === "/home"} />
      <SpaLink label="Recorder" to="/app" active={path === "/app"} />
      <SpaLink label="Translate" to="/translate" active={path === "/translate"} />
      <button type="button" onClick={() => navigate(uploadTarget)}>
        Upload
      </button>
      <button type="button" onClick={() => navigate("/app?recordings=1")}>
        My recordings
      </button>
      {user.role === "admin" && (
        <>
          <div className={styles.navGroup}>Admin</div>
          <SpaLink label="Admin console" to="/admin" active={path === "/admin"} />
          <button type="button" onClick={() => navigate("/admin?tab=recordings")}>
            All Recordings
          </button>
        </>
      )}
    </nav>
  );
}
