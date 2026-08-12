// GET /api/admin/users item shape, verified against
// voice_transcriber/routes_api.py::admin_list_users.
export interface AdminUser {
  id: string;
  username: string;
  full_name: string;
  email: string;
  role: "user" | "admin";
  is_active: boolean;
  created_at: string;
  last_login: string | null;
  last_seen: string | null;
  recording_count: number;
}

export interface NewUserBody {
  username: string;
  full_name: string;
  email: string;
  password: string;
  role: "user" | "admin";
}
