import type { ReactElement, ReactNode } from "react";
import { useAppSelector } from "../../app/hooks";

interface RequireAuthProps {
  children: ReactNode;
  /** Also requires user.role === "admin", redirecting to /app otherwise -
   * matches admin.html's `if (me.role !== 'admin') location.replace('/app')`. */
  adminOnly?: boolean;
}

// Mirrors the old pages' synchronous "no token/user -> location.replace"
// check at the top of their inline script. authSlice's initial state is
// already hydrated from sessionStorage before the store exists (see
// authSlice.ts), so this decision is made on first render - the protected
// page's content and data fetches never mount in the unauthenticated case.
//
// Calling location.replace during render is an intentional, narrow
// exception scoped to this one guard, chosen so it composes with
// react-router's <Route> element as more pages migrate, rather than
// duplicating a pre-render check in main.tsx per route.
export function RequireAuth({ children, adminOnly }: RequireAuthProps): ReactElement | null {
  const token = useAppSelector((state) => state.auth.token);
  const user = useAppSelector((state) => state.auth.user);

  if (!token || !user) {
    window.location.replace("/login");
    return null;
  }

  if (adminOnly && user.role !== "admin") {
    window.location.replace("/app");
    return null;
  }

  return <>{children}</>;
}
