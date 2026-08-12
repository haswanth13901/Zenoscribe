import { createApi, fetchBaseQuery, type BaseQueryFn, type FetchArgs, type FetchBaseQueryError } from "@reduxjs/toolkit/query/react";
import type { RootState } from "../app/store";
import { clearCredentials } from "../features/auth/authSlice";

// An absolute same-origin URL rather than a bare "/api": real browsers
// resolve a relative fetch() against document.baseURI, but Node's fetch
// (used under jsdom in tests) has no implicit base and throws on a
// relative input - computing the origin explicitly works identically in
// the browser (dev, proxied via Vite, and prod) and makes the base query
// testable under Vitest without any test-only branching.
const rawBaseQuery = fetchBaseQuery({
  baseUrl: `${window.location.origin}/api`,
  prepareHeaders: (headers, { getState }) => {
    const token = (getState() as RootState).auth.token;
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return headers;
  },
});

// Direct replacement for the three near-identical api(path, opts) fetch
// wrappers hand-rolled on home.html/index.html/admin.html today: one place
// that injects the Authorization header and reacts to a 401 exactly like
// the old wrappers did (clear session, hard-redirect to /login).
const baseQueryWith401Handling: BaseQueryFn<string | FetchArgs, unknown, FetchBaseQueryError> = async (
  args,
  api,
  extraOptions,
) => {
  const result = await rawBaseQuery(args, api, extraOptions);
  if (result.error?.status === 401) {
    api.dispatch(clearCredentials());
    window.location.href = "/login";
  }
  return result;
};

export const baseApi = createApi({
  reducerPath: "api",
  baseQuery: baseQueryWith401Handling,
  tagTypes: ["Recordings", "Users"],
  // Future page migrations extend this via baseApi.injectEndpoints(...)
  // instead of re-deriving auth-header/401 handling per page.
  endpoints: () => ({}),
});
