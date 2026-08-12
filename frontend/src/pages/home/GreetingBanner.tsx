import type { ReactElement } from "react";
import { formatTodayLabel, getGreeting } from "../../lib/greeting";
import type { AuthUser } from "../../features/auth/types";
import styles from "./HomePage.module.css";

interface GreetingBannerProps {
  user: AuthUser;
  now: Date;
}

export function GreetingBanner({ user, now }: GreetingBannerProps): ReactElement {
  return (
    <div className={styles.greet}>
      <h1>{getGreeting(now, user.full_name || user.username)}</h1>
      <span className={styles.date}>{formatTodayLabel(now)}</span>
    </div>
  );
}
