import os
import sys
sys.path.insert(0, os.getcwd())
from fastapi.testclient import TestClient
from server import app

client = TestClient(app)

# Upload UI handlers and alert strings live in static/upload.js, not inline
# in the /app HTML, so fetch that script and assert against it.
r = client.get('/static/upload.js')
assert r.status_code == 200, f'GET /static/upload.js failed: {r.status_code}'
js = r.text

assert 'doUpload' in js or 'doTranscribeTranslate' in js, 'Upload handler not found in upload.js'
assert "Upload failed" in js, 'Upload failed alert text not found'
assert "Upload error" in js, 'Upload error alert text not found'

print('TC-14 upload UI alert presence test passed')
