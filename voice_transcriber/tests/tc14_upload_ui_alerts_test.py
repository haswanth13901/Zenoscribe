import os
import sys
sys.path.insert(0, os.getcwd())
from fastapi.testclient import TestClient
from server import app

client = TestClient(app)

# Fetch main app page and assert upload UI handlers and alert strings are present
r = client.get('/app')
assert r.status_code == 200, f'GET /app failed: {r.status_code}'
html = r.text

assert 'doUpload' in html or 'doTranscribeTranslate' in html, 'Upload handler not found in page'
assert "Upload failed" in html, 'Upload failed alert text not found'
assert "Upload error" in html, 'Upload error alert text not found'

print('TC-14 upload UI alert presence test passed')
