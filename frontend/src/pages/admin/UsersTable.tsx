import { useState, type ReactElement } from "react";
import type { SerializedError } from "@reduxjs/toolkit";
import type { FetchBaseQueryError } from "@reduxjs/toolkit/query";
import { useDeleteUserMutation, useGetUsersQuery, useResetPasswordMutation, useSetActiveMutation } from "../../features/users/usersApi";
import type { AdminUser } from "../../features/users/types";
import { extractApiError } from "../../lib/apiError";
import { fmtDate } from "../../lib/fmtDate";
import { presence } from "../../lib/presence";
import { PresenceDot } from "./PresenceDot";
import styles from "./UsersTable.module.css";

type ActionMessage = { text: string; ok: boolean } | null;

interface UserRowProps {
  user: AdminUser;
  onMessage: (message: ActionMessage) => void;
}

function errorMessage(err: unknown): ActionMessage {
  return { text: extractApiError(err as FetchBaseQueryError | SerializedError).message, ok: false };
}

// Row actions keep the original's native window.prompt()/window.confirm()
// gestures, but replace every alert() for error/success reporting with
// inline state (via onMessage) - the same fix-while-porting bar /home and
// /app already established. This is also where the server's self/last-
// admin guard-rail 400s ("Cannot deactivate yourself", "Cannot delete the
// last admin", etc.) land and must render inline.
function UserRow({ user, onMessage }: UserRowProps): ReactElement {
  const [resetPassword, { isLoading: isResetting }] = useResetPasswordMutation();
  const [setActive, { isLoading: isToggling }] = useSetActiveMutation();
  const [deleteUser, { isLoading: isDeleting }] = useDeleteUserMutation();

  async function handleResetPassword() {
    const pw = window.prompt(`New password for ${user.username} (min 8 characters):`);
    if (!pw) return;
    onMessage(null);
    try {
      await resetPassword({ id: user.id, password: pw }).unwrap();
      onMessage({ text: "Password updated.", ok: true });
    } catch (err) {
      onMessage(errorMessage(err));
    }
  }

  async function handleToggleActive() {
    onMessage(null);
    try {
      await setActive({ id: user.id, is_active: !user.is_active }).unwrap();
    } catch (err) {
      onMessage(errorMessage(err));
    }
  }

  async function handleDelete() {
    if (!window.confirm(`Delete ${user.username} and their ${user.recording_count} recording(s)? This cannot be undone.`)) return;
    onMessage(null);
    try {
      await deleteUser(user.id).unwrap();
    } catch (err) {
      onMessage(errorMessage(err));
    }
  }

  return (
    <tr>
      <td>
        <strong>{user.username}</strong>
        {user.full_name && <div className={styles.subtext}>{user.full_name}</div>}
      </td>
      <td className={styles.muted}>{user.email || "—"}</td>
      <td>
        <span className={`${styles.tag} ${user.role === "admin" ? styles.tagAdmin : ""}`}>{user.role}</span>
      </td>
      <td>
        <span className={`${styles.tag} ${user.is_active ? styles.tagOn : styles.tagOff}`}>
          {user.is_active ? "active" : "disabled"}
        </span>
      </td>
      <td>{user.recording_count}</td>
      <td>
        <PresenceDot presence={presence(user.last_seen)} />
      </td>
      <td className={styles.muted}>{fmtDate(user.last_login)}</td>
      <td>
        <div className={styles.rowActions}>
          <button type="button" onClick={handleResetPassword} disabled={isResetting}>
            Reset password
          </button>
          <button type="button" onClick={handleToggleActive} disabled={isToggling}>
            {user.is_active ? "Deactivate" : "Activate"}
          </button>
          <button type="button" className={styles.danger} onClick={handleDelete} disabled={isDeleting}>
            Delete
          </button>
        </div>
      </td>
    </tr>
  );
}

export function UsersTable(): ReactElement {
  const { data: users, isLoading, isError, refetch } = useGetUsersQuery();
  const [actionMessage, setActionMessage] = useState<ActionMessage>(null);

  return (
    <div className={styles.panel}>
      <h2 className={styles.heading}>Users</h2>

      {isLoading && <div className={styles.loading}>Loading...</div>}

      {!isLoading && isError && (
        <div className={styles.errorState}>
          Couldn't load users.
          <button type="button" className={styles.retryBtn} onClick={refetch}>
            Try again
          </button>
        </div>
      )}

      {!isLoading && !isError && users && (
        <table>
          <thead>
            <tr>
              <th>User</th>
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
              <th>Recordings</th>
              <th>Presence</th>
              <th>Last login</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <UserRow key={u.id} user={u} onMessage={setActionMessage} />
            ))}
          </tbody>
        </table>
      )}

      {actionMessage && <div className={actionMessage.ok ? styles.actionOk : styles.actionError}>{actionMessage.text}</div>}
    </div>
  );
}
