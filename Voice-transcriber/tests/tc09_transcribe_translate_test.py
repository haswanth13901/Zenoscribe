import os
import sys
import io
import wave
sys.path.insert(0, os.getcwd())
from fastapi.testclient import TestClient
import db, auth, routes_api
from server import app

# Monkeypatch routes_api.sx.transcribe_file to return a fake translated turns
original_transcribe = routes_api.sx.transcribe_file

def fake_transcribe_file(path, target_language=None, *args, **kwargs):
    # Simulate a successful one-way translation response with speaker turns
    return [
        {"speaker": "spk1", "text": "Hola mundo", "start": 0.0, "end": 1.0}
    ]

routes_api.sx.transcribe_file = fake_transcribe_file

client = TestClient(app)

# Setup test user
user = 'tc09_user'
password = 'TranslatePass123!'
user_id = db.create_user(user, auth.hash_password(password), full_name='TC09 User')

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

# POST to /api/transcribe/translate with a target_language - expect 200 and translated turns
resp = client.post('/api/transcribe/translate?target_language=es', headers=headers, files=files)
print('status', resp.status_code, 'body', resp.text)
assert resp.status_code == 200, f'Expected 200 OK, got {resp.status_code} {resp.text}'
json = resp.json()
assert 'turns' in json and isinstance(json['turns'], list) and len(json['turns']) == 1, 'unexpected turns structure'
assert json['turns'][0].get('text') == 'Hola mundo', f"unexpected translated text: {json['turns'][0].get('text')}"

# Cleanup
routes_api.sx.transcribe_file = original_transcribe
try:
    db.delete_user(user_id)
except Exception:
    pass

print('TC-09 transcribe+translate endpoint test passed')
