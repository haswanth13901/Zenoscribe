// Shape of POST /api/login's `user` field, and what's stored (as JSON) in
// sessionStorage.user. Verified against voice_transcriber/routes_api.py.
export interface AuthUser {
  id: string;
  username: string;
  full_name: string;
  role: "user" | "admin";
}

// GET /api/me returns this instead — same fields as AuthUser plus `email`,
// which the login response does not include. Not used by the home pilot
// yet, but recorded here since later pages (admin) will need it.
export interface MeResponse extends AuthUser {
  email: string;
}
