import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { AuthUser } from "@/features/auth/model/types";

export interface AuthState {
  token: string | null;
  user: AuthUser | null;
}

// Read synchronously at module load (not in a useEffect) so the very first
// render already knows whether the user is authenticated - this is what
// lets RequireAuth make its redirect decision before anything protected
// ever mounts, matching the old pages' top-of-script redirect.
export function loadAuthFromStorage(): AuthState {
  try {
    const token = sessionStorage.getItem("token");
    const userRaw = sessionStorage.getItem("user");
    if (token && userRaw) {
      return { token, user: JSON.parse(userRaw) as AuthUser };
    }
  } catch {
    // Malformed storage is treated the same as "not logged in".
  }
  return { token: null, user: null };
}

const initialState: AuthState = loadAuthFromStorage();

const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {
    setCredentials(state, action: PayloadAction<{ token: string; user: AuthUser }>) {
      state.token = action.payload.token;
      state.user = action.payload.user;
      sessionStorage.setItem("token", action.payload.token);
      sessionStorage.setItem("user", JSON.stringify(action.payload.user));
    },
    clearCredentials(state) {
      state.token = null;
      state.user = null;
      try {
        sessionStorage.clear();
      } catch {
        // Ignore - nothing meaningful to recover from a storage failure here.
      }
    },
  },
});

export const { setCredentials, clearCredentials } = authSlice.actions;
export default authSlice.reducer;
