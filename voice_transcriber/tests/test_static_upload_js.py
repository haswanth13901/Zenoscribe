"""Static asset check: upload.js exposes the handlers/alert copy the UI relies on.

Ports tc14_upload_ui_alerts_test.py.
"""


def test_upload_js_exposes_handlers_and_alert_text(client):
    r = client.get("/static/upload.js")
    assert r.status_code == 200
    js = r.text
    assert "doUpload" in js or "doTranscribeTranslate" in js
    assert "Upload failed" in js
    assert "Upload error" in js
