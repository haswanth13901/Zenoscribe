import { useState, type ReactElement } from "react";
import type { SerializedError } from "@reduxjs/toolkit";
import type { FetchBaseQueryError } from "@reduxjs/toolkit/query";
import { useCreateUserMutation } from "@/entities/user/api/usersApi";
import { extractApiError } from "@/shared/lib/apiError";
import styles from "./CreateUserForm.module.css";

// Port of admin.html's "Register a user" panel. No client-side validation
// beyond trim (matches the original exactly) - server 400s/409s surface in
// the inline .msg area, which the original already did without alert(), so
// this one needed no fix-while-porting, just a straight port.
export function CreateUserForm(): ReactElement {
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"user" | "admin">("user");
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);

  const [createUser, { isLoading }] = useCreateUserMutation();

  async function handleCreate() {
    setMessage(null);
    const body = {
      username: username.trim(),
      full_name: fullName.trim(),
      email: email.trim(),
      password,
      role,
    };
    try {
      await createUser(body).unwrap();
      setMessage({ text: `Created ${body.username}.`, ok: true });
      setUsername("");
      setFullName("");
      setEmail("");
      setPassword("");
    } catch (err) {
      setMessage({
        text: extractApiError(err as FetchBaseQueryError | SerializedError).message,
        ok: false,
      });
    }
  }

  return (
    <div className={styles.panel}>
      <h2 className={styles.heading}>Register a user</h2>
      <div className={styles.grid}>
        <div>
          <label htmlFor="new-user-username">Username</label>
          <input
            id="new-user-username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="new-user-fullname">Full name</label>
          <input
            id="new-user-fullname"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="new-user-email">Email</label>
          <input
            id="new-user-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="new-user-password">Password (min 8)</label>
          <input
            id="new-user-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="new-user-role">Role</label>
          <select
            id="new-user-role"
            value={role}
            onChange={(e) => setRole(e.target.value as "user" | "admin")}
          >
            <option value="user">User</option>
            <option value="admin">Admin</option>
          </select>
        </div>
      </div>
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.primary}
          onClick={handleCreate}
          disabled={isLoading}
        >
          Create user
        </button>
      </div>
      {message && (
        <div className={`${styles.msg} ${message.ok ? styles.msgOk : styles.msgErr}`}>
          {message.text}
        </div>
      )}
    </div>
  );
}
