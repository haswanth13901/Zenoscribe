import os
import sys
import io
import wave
sys.path.insert(0, os.getcwd())
from fastapi.testclient import TestClient
import db, auth, routes_api
from server import app

# Monkeypatch routes_api.sx.transcribe_file to return different responses
original_transcribe = routes_api.sx.transcribe_file

def fake_transcribe_file(path, target_language=None, *args, **kwargs):
    # Simulate STT when no target_language, and translation when provided
    if target_language:
        return [{"speaker": "spk1", "text": "Bonjour le monde", "start": 0.0, "end": 1.0}]
    return [{"speaker": "spk1", "text": "Hello world", "start": 0.0, "end": 1.0}]

routes_api.sx.transcribe_file = fake_transcribe_file

client = TestClient(app)

# Setup test user
user = 'tc10_user'
password = 'UploadPass123!'
user_id = db.create_user(user, auth.hash_password(password), full_name='TC10 User')

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

# 1) Transcribe (no target_language)
resp = client.post('/api/transcribe/translate', headers=headers, files=files)
print('transcribe status', resp.status_code, 'body', resp.text)
assert resp.status_code == 200, f'Expected 200 OK for transcribe, got {resp.status_code} {resp.text}'
json = resp.json()
assert 'turns' in json and json['turns'][0].get('text') == 'Hello world'

# Rewind buffer for second upload
buf.seek(0)
files = {'file': ('test.wav', buf, 'audio/wav')}

# 2) Transcribe & Translate (target_language=fr)
resp2 = client.post('/api/transcribe/translate?target_language=fr', headers=headers, files=files)
print('translate status', resp2.status_code, 'body', resp2.text)
assert resp2.status_code == 200, f'Expected 200 OK for translate, got {resp2.status_code} {resp2.text}'
json2 = resp2.json()
assert 'turns' in json2 and json2['turns'][0].get('text') == 'Bonjour le monde'

# Cleanup
routes_api.sx.transcribe_file = original_transcribe
try:
    db.delete_user(user_id)
except Exception:
    pass

print('TC-10 upload UI flow test passed')
