import { useCallback, useEffect, useRef, useState, type MouseEvent, type ReactElement } from "react";
import { useAppDispatch } from "../../app/hooks";
import { clearCredentials } from "../../features/auth/authSlice";
import type { AuthUser } from "../../features/auth/types";
import { getInitials } from "../../lib/initials";
import { ThemeToggleButton } from "../theme/ThemeToggleButton";
import styles from "./Header.module.css";

interface HeaderProps {
  user: AuthUser;
}

// Port of header.js as a props-driven component: brand/home link, account
// chip with initials avatar + sign-out dropdown. Ported behavior 1:1,
// including using `username` (not full_name) for both the displayed name
// and the avatar initials, matching what home.html/header.js do today.
//
// The trigger and the dropdown menu are siblings inside .acctWrap, not
// parent/child - nesting the "Sign out" <button> inside another
// interactive element (whether a real <button> or a role="button" div)
// is an accessibility anti-pattern (ambiguous accessible name, broken
// nested-control semantics for assistive tech).
export function Header({ user }: HeaderProps): ReactElement {
  const dispatch = useAppDispatch();
  const [menuOpen, setMenuOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onDocClick(e: globalThis.MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    function onKeyDown(e: globalThis.KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("click", onDocClick);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen]);

  const toggleMenu = useCallback((e: MouseEvent) => {
    e.stopPropagation();
    setMenuOpen((open) => !open);
  }, []);

  const signOut = useCallback(
    (e: MouseEvent) => {
      e.stopPropagation();
      dispatch(clearCredentials());
      window.location.href = "/login";
    },
    [dispatch],
  );

  return (
    <header id="appHeader" className={styles.header}>
      <button type="button" className={styles.homeBtn} title="Home" onClick={() => window.location.assign("/home")}>
        <span className={styles.dot} />
        <span>ZENOSCRIBE</span>
      </button>
      <span className={styles.spacer} />
      <ThemeToggleButton />
      <div ref={wrapRef} className={styles.acctWrap}>
        <button
          type="button"
          className={`${styles.acct} ${menuOpen ? styles.open : ""}`}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={toggleMenu}
        >
          <span className={styles.avatar}>{getInitials(user.username)}</span>
          <span className={styles.who}>{user.username}</span>
        </button>
        {menuOpen && (
          <div className={styles.menu} role="menu">
            <button type="button" onClick={signOut}>
              Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
