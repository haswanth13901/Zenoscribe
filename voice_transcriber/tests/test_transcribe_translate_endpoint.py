"""POST /api/transcribe/translate: plain vs translated text, and fault mapping.

Ports tc09_transcribe_translate_test.py, tc10_upload_ui_test.py,
tc11_upload_timeout_test.py, and tc12_upload_runtime_error_test.py.
"""
from voice_transcriber import routes_api


def _login(client, username, password):
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _fake_transcribe(path, target_language=None, *args, **kwargs):
    if target_language:
        return [{"speaker": "spk1", "text": "Bonjour le monde", "start": 0.0, "end": 1.0}]
    return [{"speaker": "spk1", "text": "Hello world", "start": 0.0, "end": 1.0}]


def _raise_timeout(path, target_language=None, *args, **kwargs):
    raise TimeoutError("simulated upstream timeout")


def _raise_runtime_error(path, target_language=None, *args, **kwargs):
    raise RuntimeError("simulated upstream runtime error")


def test_translate_returns_translated_turns(client, make_user, make_wav, monkeypatch):
    def fake_es(path, target_language=None, *a, **kw):
        assert target_language == "es"
        return [{"speaker": "spk1", "text": "Hola mundo", "start": 0.0, "end": 1.0}]
    monkeypatch.setattr(routes_api.sx, "transcribe_file", fake_es)

    make_user("translate_user", "TranslatePass123!")
    headers = _login(client, "translate_user", "TranslatePass123!")
    r = client.post("/api/transcribe/translate?target_language=es", headers=headers,
                     files={"file": ("test.wav", make_wav(), "audio/wav")})
    assert r.status_code == 200
    turns = r.json()["turns"]
    assert len(turns) == 1
    assert turns[0]["text"] == "Hola mundo"


def test_transcribe_without_target_language_returns_english(client, make_user, make_wav, monkeypatch):
    monkeypatch.setattr(routes_api.sx, "transcribe_file", _fake_transcribe)
    make_user("plain_user", "PlainPass123!")
    headers = _login(client, "plain_user", "PlainPass123!")
    r = client.post("/api/transcribe/translate", headers=headers,
                     files={"file": ("test.wav", make_wav(), "audio/wav")})
    assert r.status_code == 200
    assert r.json()["turns"][0]["text"] == "Hello world"


def test_transcribe_with_target_language_returns_translated_text(client, make_user, make_wav, monkeypatch):
    monkeypatch.setattr(routes_api.sx, "transcribe_file", _fake_transcribe)
    make_user("fr_user", "FrPass123!")
    headers = _login(client, "fr_user", "FrPass123!")
    r = client.post("/api/transcribe/translate?target_language=fr", headers=headers,
                     files={"file": ("test.wav", make_wav(), "audio/wav")})
    assert r.status_code == 200
    assert r.json()["turns"][0]["text"] == "Bonjour le monde"


def test_translate_timeout_maps_to_504(client, make_user, make_wav, monkeypatch):
    monkeypatch.setattr(routes_api.sx, "transcribe_file", _raise_timeout)
    make_user("translate_timeout_user", "TranslateTimeoutPass123!")
    headers = _login(client, "translate_timeout_user", "TranslateTimeoutPass123!")
    r = client.post("/api/transcribe/translate", headers=headers,
                     files={"file": ("test.wav", make_wav(), "audio/wav")})
    assert r.status_code == 504


def test_translate_runtime_error_maps_to_502(client, make_user, make_wav, monkeypatch):
    monkeypatch.setattr(routes_api.sx, "transcribe_file", _raise_runtime_error)
    make_user("translate_runtime_user", "TranslateRuntimePass123!")
    headers = _login(client, "translate_runtime_user", "TranslateRuntimePass123!")
    r = client.post("/api/transcribe/translate", headers=headers,
                     files={"file": ("test.wav", make_wav(), "audio/wav")})
    assert r.status_code == 502
