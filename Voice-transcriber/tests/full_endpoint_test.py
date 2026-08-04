import os
import requests
import time
import json

import db
import auth
import config

BASE = "http://127.0.0.1:8000"

PASS = 0
FAIL = 0

def ok(msg):
    global PASS
    print("PASS:", msg)
    PASS += 1

def fail(msg):
    global FAIL
    print("FAIL:", msg)
    FAIL += 1

# Create test users directly in DB
user_pwd = "TestPass123!"
admin_pwd = "AdminPass123!"

print("Creating test users...")
user_id = db.create_user("test_user_ci", auth.hash_password(user_pwd), full_name="CI Test User")
admin_id = db.create_user("test_admin_ci", auth.hash_password(admin_pwd), full_name="CI Admin", role="admin")
print("Created user_id", user_id, "admin_id", admin_id)

# Allow server to pick up DB changes
time.sleep(0.5)

# Helper to login
def login(username, password):
    r = requests.post(BASE + "/api/login", json={"username": username, "password": password})
    return r

# 1. Login as user
r = login("test_user_ci", user_pwd)
if r.status_code == 200:
    token = r.json().get("token")
    ok("login (user)")
else:
    fail(f"login (user) status {r.status_code} {r.text}")
    token = None

# 2. GET /api/me
if token:
    h = {"Authorization": f"Bearer {token}"}
    r = requests.get(BASE + "/api/me", headers=h)
    if r.status_code == 200 and r.json().get("username") == "test_user_ci":
        ok("/api/me returns correct user")
    else:
        fail(f"/api/me failed: {r.status_code} {r.text}")

# 3. GET /api/recordings (should be empty list)
if token:
    r = requests.get(BASE + "/api/recordings", headers=h)
    if r.status_code == 200 and isinstance(r.json(), list):
        ok("/api/recordings list")
    else:
        fail(f"/api/recordings failed: {r.status_code} {r.text}")

# 4. Create a dummy recording file and entry, then fetch transcript and audio
wav_name = "ci_dummy.wav"
txt_name = "ci_dummy.txt"
rec_id = "ci_rec_1"
text_content = "Hello from CI test."

# create placeholder files
rec_dir = config.RECORDINGS
rec_dir.mkdir(parents=True, exist_ok=True)
(rec_dir / txt_name).write_text(text_content, encoding="utf-8")
(rec_dir / wav_name).write_bytes(b"RIFF....WAVEfmt ")

# add recording metadata
db.add_recording(rec_id, user_id, wav_name, txt_name, time.strftime("%Y-%m-%dT%H:%M:%S"), 1.2, 1, "Hello")

# GET transcript
r = requests.get(f"{BASE}/api/recordings/{rec_id}/transcript", headers=h)
if r.status_code == 200 and text_content in r.json().get("text", ""):
    ok("/api/recordings/{id}/transcript")
else:
    fail(f"transcript failed: {r.status_code} {r.text}")

# GET audio
r = requests.get(f"{BASE}/api/recordings/{rec_id}/audio", headers=h)
if r.status_code == 200 and r.headers.get('content-type','').startswith('audio'):
    ok("/api/recordings/{id}/audio")
else:
    fail(f"audio failed: {r.status_code} {r.text}")

# 5. Login as admin and test admin endpoints
r = login("test_admin_ci", admin_pwd)
if r.status_code == 200:
    admin_token = r.json().get("token")
    ok("login (admin)")
else:
    fail(f"login (admin) {r.status_code} {r.text}")
    admin_token = None

if admin_token:
    ah = {"Authorization": f"Bearer {admin_token}"}
    r = requests.get(BASE + "/api/admin/users", headers=ah)
    if r.status_code == 200 and isinstance(r.json(), list):
        ok("/api/admin/users list")
    else:
        fail(f"/api/admin/users failed: {r.status_code} {r.text}")

    # create a new user via admin API
    r = requests.post(BASE + "/api/admin/users", headers=ah, json={"username":"api_created_user","password":"ApiPass123!","full_name":"API Created","email":"ci@example.com","role":"user"})
    if r.status_code == 200 and r.json().get("id"):
        created_user_id = r.json()["id"]
        ok("POST /api/admin/users create")
    else:
        fail(f"admin create user failed: {r.status_code} {r.text}")
        created_user_id = None

    # reset password for created user
    if created_user_id:
        r = requests.post(BASE + f"/api/admin/users/{created_user_id}/password", headers=ah, json={"password":"NewPass123!"})
        if r.status_code == 200 and r.json().get("ok"):
            ok("admin reset password")
        else:
            fail(f"admin reset password failed: {r.status_code} {r.text}")

    # deactivate/reactivate created user
    if created_user_id:
        r = requests.post(BASE + f"/api/admin/users/{created_user_id}/active", headers=ah, json={"is_active": False})
        if r.status_code == 200 and r.json().get("ok"):
            ok("admin set active=false")
        else:
            fail(f"admin set active false failed: {r.status_code} {r.text}")
        r = requests.post(BASE + f"/api/admin/users/{created_user_id}/active", headers=ah, json={"is_active": True})
        if r.status_code == 200 and r.json().get("ok"):
            ok("admin set active=true")
        else:
            fail(f"admin set active true failed: {r.status_code} {r.text}")

    # delete the created user
    if created_user_id:
        r = requests.delete(BASE + f"/api/admin/users/{created_user_id}", headers=ah)
        if r.status_code == 200 and r.json().get("ok"):
            ok("admin delete user")
        else:
            fail(f"admin delete user failed: {r.status_code} {r.text}")

# Cleanup: remove test users and files
print("Cleaning up test data...")
try:
    db.delete_user(user_id)
    db.delete_user(admin_id)
except Exception as e:
    print("Cleanup error:", e)
try:
    (rec_dir / txt_name).unlink(missing_ok=True)
    (rec_dir / wav_name).unlink(missing_ok=True)
except Exception:
    pass

print(f"Finished: {PASS} passed, {FAIL} failed")
if FAIL:
    raise SystemExit(1)
