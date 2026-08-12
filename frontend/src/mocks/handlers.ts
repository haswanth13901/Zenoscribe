import { http, HttpResponse } from "msw";
import type { Recording } from "../features/recordings/types";
import type { AdminUser } from "../features/users/types";

export const sampleRecordings: Recording[] = [
  {
    id: "rec-1",
    username: "ada",
    user_id: "u1",
    started_at: new Date().toISOString(),
    duration: 125,
    turn_count: 4,
    preview: "Let's talk about the launch plan",
  },
];

export const sampleUsers: AdminUser[] = [
  {
    id: "u1",
    username: "ada",
    full_name: "Ada Lovelace",
    email: "ada@example.com",
    role: "admin",
    is_active: true,
    created_at: new Date().toISOString(),
    last_login: new Date().toISOString(),
    last_seen: new Date().toISOString(),
    recording_count: 3,
  },
  {
    id: "u2",
    username: "grace",
    full_name: "Grace Hopper",
    email: "",
    role: "user",
    is_active: false,
    created_at: new Date().toISOString(),
    last_login: null,
    last_seen: null,
    recording_count: 0,
  },
];

export const handlers = [
  http.get("/api/admin/users", () => HttpResponse.json(sampleUsers)),
  http.post("/api/admin/users", async ({ request }) => {
    const body = (await request.json()) as { username: string; role: string };
    return HttpResponse.json({ id: "new-id", username: body.username, role: body.role });
  }),
  http.post("/api/admin/users/:id/password", () => HttpResponse.json({ ok: true })),
  http.post("/api/admin/users/:id/active", () => HttpResponse.json({ ok: true })),
  http.delete("/api/admin/users/:id", () => HttpResponse.json({ ok: true, removed_recordings: 0 })),
  http.get("/api/recordings", () => HttpResponse.json(sampleRecordings)),
  http.get("/api/recordings/:id/transcript", ({ params }) =>
    HttpResponse.json({ id: params.id, text: "[0.0s] user-1: hello\n[1.2s] user-2: hi" }),
  ),
  http.delete("/api/recordings/:id", () => HttpResponse.json({ ok: true })),
  http.get("/api/recordings/:id/audio", () => HttpResponse.arrayBuffer(new ArrayBuffer(4), { headers: { "Content-Type": "audio/wav" } })),
  http.get("/api/languages", () =>
    HttpResponse.json({
      languages: [
        { code: "en", name: "English" },
        { code: "es", name: "Spanish" },
      ],
      voices: ["Maya", "Adrian"],
    }),
  ),
  http.post("/api/transcribe/translate", async ({ request }) =>
    HttpResponse.json({ turns: [{ text: `transcribed:${new URL(request.url).searchParams.get("target_language") ?? "none"}` }] }),
  ),
];
