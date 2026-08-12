import { useEffect, useState, type ReactElement } from "react";
import { useSearchParams } from "react-router-dom";
import { useAppSelector } from "../../app/hooks";
import { AppLayout } from "../../components/layout/AppLayout";
import { UploadPanel } from "../../features/transcribe/UploadPanel";
import { AdminRecordingsPane } from "./AdminRecordingsPane";
import { CreateUserForm } from "./CreateUserForm";
import { UsersTable } from "./UsersTable";
import styles from "./AdminPage.module.css";

type Tab = "users" | "recordings";

// Rendered only inside <RequireAuth adminOnly>, so `user` is guaranteed
// non-null and role==="admin" here.
export function AdminPage(): ReactElement {
  const user = useAppSelector((s) => s.auth.user)!;
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState<Tab>("users");
  const [uploadOpen, setUploadOpen] = useState(false);

  // Deep-links from the sidebar (?tab=recordings, ?upload=1), mirroring
  // RecorderPage's exact pattern: set state, then clear the param so a
  // repeat click while already on /admin (no location change otherwise)
  // still re-fires.
  useEffect(() => {
    let changed = false;
    if (searchParams.get("tab") === "recordings") {
      setTab("recordings");
      changed = true;
    }
    if (searchParams.get("upload") === "1") {
      setUploadOpen(true);
      changed = true;
    }
    if (changed) {
      setSearchParams(
        (prev) => {
          prev.delete("tab");
          prev.delete("upload");
          return prev;
        },
        { replace: true },
      );
    }
  }, [searchParams, setSearchParams]);

  return (
    <AppLayout user={user}>
      <nav className={styles.tabs}>
        <button type="button" data-testid="tab-users" className={tab === "users" ? styles.on : undefined} onClick={() => setTab("users")}>
          Users
        </button>
        <button
          type="button"
          data-testid="tab-recordings"
          className={tab === "recordings" ? styles.on : undefined}
          onClick={() => setTab("recordings")}
        >
          All Recordings
        </button>
      </nav>

      <main className={styles.main}>
        {tab === "users" ? (
          <>
            <CreateUserForm />
            <UsersTable />
          </>
        ) : (
          <AdminRecordingsPane />
        )}
      </main>

      <UploadPanel open={uploadOpen} onClose={() => setUploadOpen(false)} />
    </AppLayout>
  );
}
