import { beforeEach, describe, expect, it } from "vitest";
import authReducer, {
  clearCredentials,
  loadAuthFromStorage,
  setCredentials,
} from "@/features/auth/model/authSlice";
import type { AuthUser } from "@/features/auth/model/types";

const user: AuthUser = { id: "u1", username: "ada", full_name: "Ada Lovelace", role: "user" };

describe("authSlice reducers", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("setCredentials stores token/user in state and sessionStorage", () => {
    const state = authReducer(undefined, setCredentials({ token: "tok", user }));
    expect(state).toEqual({ token: "tok", user });
    expect(sessionStorage.getItem("token")).toBe("tok");
    expect(JSON.parse(sessionStorage.getItem("user")!)).toEqual(user);
  });

  it("clearCredentials wipes state and sessionStorage", () => {
    const loggedIn = authReducer(undefined, setCredentials({ token: "tok", user }));
    const state = authReducer(loggedIn, clearCredentials());
    expect(state).toEqual({ token: null, user: null });
    expect(sessionStorage.getItem("token")).toBeNull();
    expect(sessionStorage.getItem("user")).toBeNull();
  });
});

// authSlice's initial state is loadAuthFromStorage() evaluated once at
// module load - exercised directly here (rather than by re-importing the
// module to re-trigger that module-level call) since it's a pure read of
// current sessionStorage state.
describe("loadAuthFromStorage", () => {
  it("starts logged-out when sessionStorage is empty", () => {
    sessionStorage.clear();
    expect(loadAuthFromStorage()).toEqual({ token: null, user: null });
  });

  it("hydrates from sessionStorage when both keys are present", () => {
    sessionStorage.setItem("token", "existing-token");
    sessionStorage.setItem("user", JSON.stringify(user));
    expect(loadAuthFromStorage()).toEqual({ token: "existing-token", user });
  });

  it("treats malformed stored user JSON as logged-out", () => {
    sessionStorage.setItem("token", "tok");
    sessionStorage.setItem("user", "{not-json");
    expect(loadAuthFromStorage()).toEqual({ token: null, user: null });
  });
});
