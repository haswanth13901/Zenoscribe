import os
import sys
import tempfile
import wave
import io
sys.path.insert(0, os.getcwd())
from fastapi.testclient import TestClient
import db, auth, routes_api
from server import app

# Monkeypatch routes_api.sx.transcribe_file to simulate TimeoutError
original_transcribe = routes_api.sx.transcribe_file

def fake_transcribe_file(path, poll_interval=1.0, timeout=5, language_hints=("en",)):
    raise TimeoutError("simulated upstream timeout")

routes_api.sx.transcribe_file = fake_transcribe_file

client = TestClient(app)

# Setup test user
user = 'tc07_user'
password = 'TimeoutPass123!'
user_id = db.create_user(user, auth.hash_password(password), full_name='TC07 User')

# Login to obtain token
r = client.post('/api/login', json={'username': user, 'password': password})
assert r.status_code == 200, f'login failed: {r.status_code} {r.text}'
token = r.json().get('token')
headers = {'Authorization': f'Bearer {token}'}

# Create an in-memory valid WAV file
buf = io.BytesIO()
with wave.open(buf, 'wb') as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)
    wf.writeframes((b'\x00\x00') * 16000)
buf.seek(0)

files = {'file': ('test.wav', buf, 'audio/wav')}

# POST to /api/transcribe - expect 504 due to TimeoutError mapping
resp = client.post('/api/transcribe', headers=headers, files=files)
print('status', resp.status_code, 'body', resp.text)
assert resp.status_code == 504, f'Expected 504 Gateway Timeout, got {resp.status_code} {resp.text}'

# Cleanup: restore original function and delete user
routes_api.sx.transcribe_file = original_transcribe
try:
    db.delete_user(user_id)
except Exception:
    pass

print('TC-07 API timeout mapping test passed')
