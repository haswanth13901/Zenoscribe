import os
import sys
import io
import wave
sys.path.insert(0, os.getcwd())
from fastapi.testclient import TestClient
import db, auth, routes_api
from server import app

# Monkeypatch routes_api.sx.transcribe_file to raise RuntimeError
original_transcribe = routes_api.sx.transcribe_file

def fake_runtime_error(path, target_language=None, *args, **kwargs):
    raise RuntimeError("simulated upstream runtime error")

routes_api.sx.transcribe_file = fake_runtime_error

client = TestClient(app)

# Setup test user
user = 'tc12_user'
password = 'RuntimeUploadPass123!'
user_id = db.create_user(user, auth.hash_password(password), full_name='TC12 User')

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

# POST to /api/transcribe/translate - expect 502 due to RuntimeError mapping
resp = client.post('/api/transcribe/translate', headers=headers, files=files)
print('status', resp.status_code, 'body', resp.text)
assert resp.status_code == 502, f'Expected 502 Bad Gateway, got {resp.status_code} {resp.text}'

# Cleanup
routes_api.sx.transcribe_file = original_transcribe
try:
    db.delete_user(user_id)
except Exception:
    pass

print('TC-12 upload runtime error mapping test passed')
