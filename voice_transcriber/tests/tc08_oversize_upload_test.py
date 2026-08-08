import os
import sys
import io
import tempfile
import wave
sys.path.insert(0, os.getcwd())
from fastapi.testclient import TestClient
import db, auth, routes_api, config
from server import app

# Use a dedicated temp directory so we can assert no temp files remain.
with tempfile.TemporaryDirectory() as td:
    original_NTF = tempfile.NamedTemporaryFile
    def wrapped_NTF(*args, **kwargs):
        return original_NTF(*args, dir=td, **kwargs)
    tempfile.NamedTemporaryFile = wrapped_NTF
    try:
        # Make MAX_UPLOAD_SIZE small for the test
        original_max = config.MAX_UPLOAD_SIZE
        config.MAX_UPLOAD_SIZE = 1024  # 1 KB

        client = TestClient(app)

        # Setup user
        user = 'tc08_user'
        password = 'OversizePass1!'
        user_id = db.create_user(user, auth.hash_password(password), full_name='TC08 User')
        r = client.post('/api/login', json={'username': user, 'password': password})
        assert r.status_code == 200
        token = r.json().get('token')
        headers = {'Authorization': f'Bearer {token}'}

        # Create a WAV slightly larger than MAX_UPLOAD_SIZE
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            # produce ~2KB of data
            wf.writeframes((b'\x00\x00') * 1100)
        buf.seek(0)

        files = {'file': ('big.wav', buf, 'audio/wav')}
        resp = client.post('/api/transcribe', headers=headers, files=files)
        print('status', resp.status_code, resp.text)
        assert resp.status_code == 413, f'Expected 413, got {resp.status_code} {resp.text}'

        # Ensure no temp files remain in our temp dir
        remaining = os.listdir(td)
        print('temp dir contents after request:', remaining)
        assert len(remaining) == 0, f'Temporary files left behind: {remaining}'

    finally:
        # restore
        tempfile.NamedTemporaryFile = original_NTF
        config.MAX_UPLOAD_SIZE = original_max
        try:
            db.delete_user(user_id)
        except Exception:
            pass

print('TC-08 passed: oversized uploads rejected and temp file cleaned up')
