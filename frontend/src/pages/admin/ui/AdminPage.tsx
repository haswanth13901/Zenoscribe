import { useEffect, useState, type ReactElement } from "react";
import { useSearchParams } from "react-router-dom";
import { useAppSelector } from "@/app/hooks";
import { AppLayout } from "@/widgets/app-layout/ui/AppLayout";
import { AdminRecordingsPane } from "@/pages/admin/ui/AdminRecordingsPane";
import { CreateUserForm } from "@/pages/admin/ui/CreateUserForm";
import { UsersTable } from "@/pages/admin/ui/UsersTable";
import styles from "./AdminPage.module.css";

type Tab = "users" | "recordings";

// Rendered only inside <RequireAuth adminOnly>, so `user` is guaranteed
// non-null and role==="admin" here.
export function AdminPage(): ReactElement {
  const user = useAppSelector((s) => s.auth.user)!;
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState<Tab>("users");

  // Deep-link from the sidebar (?tab=recordings or ?tab=users) - the param
  // is cleared right after acting so a repeat click while already on
  // /admin (no location change otherwise) still re-fires. Admin console's
  // link carries ?tab=users rather than bare /admin for the same reason:
  // without it, clicking Admin console while already viewing the
  // Recordings tab was a same-URL no-op (React Router never re-renders,
  // since neither the path nor the search string actually changed), so the
  // page stayed stuck on Recordings.
  useEffect(() => {
    const requestedTab = searchParams.get("tab");
    if (requestedTab === "recordings" || requestedTab === "users") {
      setTab(requestedTab);
      setSearchParams(
        (prev) => {
          prev.delete("tab");
          return prev;
        },
        { replace: true },
      );
    }
  }, [searchParams, setSearchParams]);

  return (
    <AppLayout user={user} adminRecordingsTabActive={tab === "recordings"}>
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
    </AppLayout>
  );
}
