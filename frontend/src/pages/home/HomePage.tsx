import type { ReactElement } from "react";
import { useNavigate } from "react-router-dom";
import { useAppSelector } from "../../app/hooks";
import { AppLayout } from "../../components/layout/AppLayout";
import { useGetRecordingsQuery } from "../../features/recordings/recordingsApi";
import { ActionCards } from "./ActionCards";
import { GreetingBanner } from "./GreetingBanner";
import { MonthlyStats } from "./MonthlyStats";
import { RecentSessions } from "./RecentSessions";
import styles from "./HomePage.module.css";

// Rendered only inside <RequireAuth>, so `user` is guaranteed non-null here.
export function HomePage(): ReactElement {
  const user = useAppSelector((state) => state.auth.user)!;
  const navigate = useNavigate();
  const now = new Date();

  const {
    data: recordings,
    isLoading,
    isError,
    refetch,
  } = useGetRecordingsQuery({ user_id: user.id });

  return (
    <AppLayout user={user}>
      <main className={styles.main}>
        <div className={styles.wrap}>
          <GreetingBanner user={user} now={now} />

          <ActionCards />

          <div className={styles.secHead}>
            <h2>Recent sessions</h2>
            <button type="button" className={styles.viewAll} onClick={() => navigate("/app?recordings=1")}>
              View all
            </button>
          </div>
          <RecentSessions recordings={recordings} isLoading={isLoading} isError={isError} onRetry={refetch} now={now} />

          <MonthlyStats recordings={recordings} isError={isError} now={now} />
        </div>
      </main>
    </AppLayout>
  );
}
