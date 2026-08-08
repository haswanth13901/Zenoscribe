# Zenoscribe — code review notes

Went through the whole thing (server, auth, db, soniox bridge, frontend worklet). Also poked Soniox directly with the current key in `.env` — key is fine, models accept traffic. The red `error: received 1000 (OK)...` in the UI is mostly us mishandling a normal websocket close, not a dead API key.

Pin models to `stt-rt-v5` / `stt-async-v5` anyway. Docs don't list `stt-rt-preview` anymore. Still works today; don't bet on that lasting.

---

## Stuff that will actually hurt us

### 1. We show a normal Soniox close as an "error"

In `transcribe.py`, `pump_audio` only catches `WebSocketDisconnect` and `RuntimeError`. When Soniox closes cleanly (`ConnectionClosedOK` / code 1000), that exception escapes `asyncio.gather`, lands in the generic `except Exception`, and we ship it to the browser as `{type: "error", message: "..."}`.

1000 means OK. Users think the API blew up. Fix: treat upstream normal close as end-of-session, not a failure. Only surface real Soniox `error_code` / `error_message` payloads.

### 2. Frontend keeps the mic open after an error

`index.html` — on `m.type === 'error'` we update the status text and that's it. Never call `stop()`. That's why you still see the red Stop button with an error in the status. Mic + socket keep running. Call `stop()` (or at least tear down audio) when we get an error frame.

### 3. Double-start race

`running` only flips true inside `ws.onopen`. Mash Start twice before the socket opens and you get two getUserMedia streams and two `/ws` sessions. Disable the button while connecting, or bail if a start is already in flight.

### 4. Turn buffer race (watchdog vs result pump)

`flush()`, `pump_results`, and `watchdog` share `state`. There's a lock, but the speaker-takeover path drops it between slicing `buf` and calling `flush()`:

- under lock: peel `pending` off `buf`
- await flush()  ← lock released here
- under lock again: rebuild state for the new speaker

Watchdog can flush that half-edited buffer in the gap. Under real two-speaker audio this will split / duplicate / drop turns. Hold the lock across the whole takeover, or make flush re-entrant / single-flight so only one flush runs at a time.

### 5. Blocking the event loop

Inside the websocket handler we're doing sync disk and sqlite on the event loop: `wf.writeframes`, every `db.*` call, `wave.open` in `finally`, writing the `.txt`. One busy session stalls everyone else. Move DB and file IO off the loop (`asyncio.to_thread` or a writer queue). We already did this right for batch `transcribe_file`.

---

## Correctness / reliability

### 6. `gather` takes down the whole session

Any sibling task exception cancels the others. Upstream closing "OK" shouldn't nuke the client path or look like a bridge crash. Use clearer shutdown (cancel scopes / `return_exceptions` where it makes sense) and a single cleanup path.

### 7. WAV close vs cancelled writer

`finally: wf.close()` can race a cancelled `pump_audio` still in `writeframes`. Truncated or corrupt wavs, or teardown exceptions. Serialize writes through one task, or close only after the audio pump is fully done.

### 8. Failed sessions still pollute history

Bridge dies in 0.3s with zero turns → we still write wav/txt and insert a recording row. History fills with empty "(no speech detected)" junk. Skip DB registration (and maybe delete the files) if duration/turns are below a threshold, or if we exited on a hard error before any audio mattered.

### 9. Stale model names

`soniox_client.py` still has `stt-rt-preview` and `stt-async-preview`. Current Soniox docs: `stt-rt-v5`, `stt-async-v5`. Change it.

### 10. Config / API key loaded once at import

`API_KEY = os.environ["SONIOX_API_KEY"]` at module import. Editing `.env` does nothing until the process restarts. `--reload` watches Python files, not `.env`. Easy to think you rotated the key when the worker still has the old one. Either document "must restart", or read the key when opening the Soniox socket.

### 11. SpeakerLabeler fallback is weird

When `speaker` is None and we've already seen speakers, we label as `user-{len(order)}` (basically the last slot). Unlabeled tokens get pinned to the wrong person. Prefer carrying the current turn speaker, or an explicit unknown, instead of inventing a label off list length.

### 12. Pending-as-suffix assumption

`buf = buf[:len(buf) - len(carried)]` assumes `pending` is always an exact suffix of `buf`. If anything else touched `buf` (concurrent flush, bad streak math), we silently corrupt the turn text. Safer to track pending token spans / offsets, or keep pending tokens in a list and rebuild.

### 13. Batch poll has no timeout

`transcribe_file` loops forever on a stuck Soniox job. Add a max wait. Also we never clean up the uploaded remote file / job.

### 14. Last-admin check isn't atomic

`count_admins() <= 1` then delete/deactivate — two admins clicking at the same time can wipe the last admins. Needs a single transaction / conditional update.

---

## Security

### 15. JWT in the websocket query string

We already called this out in the README. Server access logs print the full URL with the token (saw it in uvicorn output). Proxies will too. Prefer a short-lived WS ticket, or auth on the first message after accept.

### 16. Login has no rate limit

`/api/login` is wide open for brute force. Add throttling / lockout before this leaves localhost.

### 17. Upload size unbounded

`POST /api/transcribe` reads the whole upload into a temp file with no size cap. Easy DoS. Cap content-length / stream with a limit.

### 18. Local admin password

Fine for local testing (`admin123`), but make sure weak seed creds never ship. New users need 8 chars; the seeded admin from env does not get the same check.

---

## Smaller stuff / hygiene

- SQLite: new connection per call, no WAL. Demo-ok; under concurrent `touch_seen` + recordings you'll get `database is locked`. Turn on WAL + busy_timeout, or one writer.
- `touch_seen` on every authenticated request is a lot of writes. Debounce presence.
- `user_from_ws(websocket: Request)` — wrong type, it's a WebSocket.
- `@app.on_event("startup")` is the old FastAPI style; move to lifespan.
- Header "Save" only dumps whatever the browser has in memory. Server already saves on session end. Confusing. Either wire Save to the last server recording or rename it "Download transcript".
- AudioContext uses the device default rate; worklet resamples to 16 kHz. Works, but requesting 16000 when the browser allows it would be cleaner.
- No tests around takeover / flush / watchdog — that's exactly where the races live.
- `record.py` is a CLI mic path the web app doesn't use. Either document it as a separate tool or drop it from the main story.

---

## What's fine

Split between auth/API and the transcription engine is clean. Recording access goes through ownership checks (404 instead of 403 so we don't leak IDs). Admin can't delete/deactivate themselves or the last admin (logic is right; atomicity isn't). Deactivated users get rejected on the next request, not only at JWT expiry. Recordings folder is not mounted as static. Diarization post-processing (majority vote + streak) is readable and tunable from `config.py`.

---

## What I'd fix first

1. Stop treating `ConnectionClosedOK` as a UI error  
2. Call `stop()` on client when we get an error frame  
3. Guard Start against double connect  
4. Pin Soniox models to v5  
5. Make takeover + flush single-flight so watchdog can't interleave  

After that: move DB/file IO off the loop, skip empty failed sessions in history, and get the JWT out of the query string before anyone deploys past localhost.
