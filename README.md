# Zenoscribe

> Every voice, clearly attributed.

Real-time speech-to-text with speaker diarization, a multi-user web UI, and an
admin console. Audio is captured in the browser, streamed to
[Soniox](https://soniox.com) for transcription and speaker separation, and
rendered live as labeled turns (`user-1`, `user-2`, ...). Sessions are saved
per user; an admin can see and manage everything.

## Features

- **Live transcription** with speaker labels, streamed over WebSocket.
- **Speaker diarization** by Soniox, with post-processing (majority vote +
  streak-based takeover) to clean up attribution at turn boundaries.
- **Recording per session** — each session saves a `.wav`, a `.txt`
  transcript, and a metadata row.
- **Accounts** — JWT login, per-user recording isolation.
- **Admin console** — register users, reset passwords, activate/deactivate,
  delete (with cascade), view all recordings, filter by user and date.
- **Presence** — `last_seen` per user, shown as online/offline in the admin
  table.
- **Date filtering** in both the user history drawer and the admin console.

## Requirements

- Python 3.10+
- A Soniox API key (https://soniox.com)
- A modern browser (Chrome/Edge/Firefox) for mic capture

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` from the template:

```bash
cp .env.example .env
```

Fill it in:

```
SONIOX_API_KEY=your_soniox_key
JWT_SECRET=<generate below>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=choose_a_strong_password
```

Generate a JWT secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

> No spaces around the `=` in `.env`. `KEY=value`, not `KEY = value` — a
> leading space becomes part of the value.

## Run

```bash
uvicorn server:app --reload --port 8000
```

Open http://localhost:8000. On first start, the admin account is created from
`ADMIN_USERNAME` / `ADMIN_PASSWORD` (watch the log to confirm). If
`ADMIN_PASSWORD` is blank, a password is generated and printed to the terminal.

- `/` or `/login` — sign in
- `/app` — recorder (all users)
- `/admin` — admin console (admins only)

Mic access requires a secure context. `localhost` counts; any other host needs
HTTPS.

## Project structure

```
server.py         Thin entrypoint: app, page routes, mounts the two routers
config.py         Paths + transcription tuning constants
transcribe.py     Realtime engine: Soniox WebSocket bridge, turn detection
routes_api.py     Auth, user administration, recording access
auth.py           JWT, bcrypt, role guards
db.py             SQLite storage (users, recordings, presence)
soniox_client.py  Soniox REST + WebSocket config, speaker labeling
static/
  login.html      Sign-in page
  index.html      Recorder + history drawer
  admin.html      Admin console
  pcm-worklet.js  Browser mic -> 16 kHz PCM
```

The two routers (`routes_api`, `transcribe`) never import each other — both
depend only on `auth`, `db`, and `config`. The transcription engine can be
retuned without touching login behaviour.

## How diarization works

Two independent layers:

1. **Soniox** does the actual speaker separation from the audio and attaches a
   speaker id to each token. This is the hard part and happens entirely on
   their side.
2. **This app** only cleans up the resulting labels — majority vote per turn,
   streak-based takeover, and carry-back — so a wrong label on the first word
   of a turn gets corrected by the rest. It cannot separate speakers Soniox
   failed to separate.

If speakers are being merged, set `DEBUG_SPEAKERS = True` in `config.py` and
watch the raw ids. If they don't alternate, the fix is upstream: pass
`num_speakers`, improve mic placement, or use separate channels. The single
biggest accuracy lever is the input audio, not the post-processing.

## Tuning turn detection

All in `config.py`:

| Constant | Meaning |
|---|---|
| `IDLE_FLUSH_SEC` | Close a turn after this much silence (default 1.6s) |
| `MAX_TURN_CHARS` | Hard cap so a turn stays readable (default 400) |
| `SENTENCE_PAUSE_SEC` | Pause required before punctuation ends a turn |
| `VOTE_MARGIN` | Consecutive tokens a new speaker needs to take over |
| `LANGUAGE_HINTS` | e.g. `["en"]`; add more for code-switching |
| `DEBUG_SONIOX` / `DEBUG_SPEAKERS` | Verbose logging toggles |

## Data & storage

- **`app.db`** — SQLite: users, recording metadata, presence. Created on first
  run; schema migrations are applied automatically at startup.
- **`recordings/`** — saved `.wav` and `.txt` files. Deliberately *not* served
  as static files; all access goes through authenticated, ownership-checked API
  routes.

Neither is committed to git (see `.gitignore`).

## Security notes

- Recordings are never publicly served; every download checks ownership
  (admins can access any; users only their own).
- Deactivating a user immediately invalidates their existing token (re-checked
  against the DB on each request, not just at expiry).
- Guards prevent an admin from deactivating/deleting themselves or removing the
  last remaining admin.
- The JWT rides in the WebSocket query string (browsers can't set headers on a
  WebSocket). Query strings can appear in server/proxy logs and are readable
  over plain HTTP. **Put this behind HTTPS before deploying beyond localhost.**
- Tokens live in `sessionStorage`, so closing the tab logs out. Switch to
  `localStorage` if you want sessions to persist.

## Batch (non-live) transcription

`soniox_client.transcribe_file(path)` uploads a `.wav`/`.mp3` and returns merged
speaker turns using the async API, which has full-file context and is more
accurate than the live path. Exposed at `POST /api/transcribe` (authenticated).

