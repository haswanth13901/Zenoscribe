import sys, os, time, tempfile, requests
sys.path.insert(0, os.getcwd())
import db, auth, config

BASE = 'http://127.0.0.1:8000'
user_pwd = 'TranscribeTest123!'
print('Creating test user...')
user_id = db.create_user('transcribe_ci_user', auth.hash_password(user_pwd), full_name='Transcribe CI')
print('user_id', user_id)
# login
r = requests.post(BASE + '/api/login', json={'username':'transcribe_ci_user','password':user_pwd})
print('login status', r.status_code)
if r.status_code!=200:
    print('login failed', r.text)
    raise SystemExit(1)
token = r.json().get('token')
headers = {'Authorization': f'Bearer {token}'}

# create a small valid WAV (1s silence, 16kHz mono) for Soniox
import wave
wav_path = os.path.join(tempfile.gettempdir(), 'ci_transcribe.wav')
with wave.open(wav_path, 'wb') as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)
    silence = (b'\x00\x00') * 16000  # 1 second
    wf.writeframes(silence)
print('WAV path', wav_path)

print('Uploading to /api/transcribe (this may take a while if Soniox processes)...')
with open(wav_path, 'rb') as f:
    files = {'file': ('ci_transcribe.wav', f, 'audio/wav')}
    try:
        resp = requests.post(BASE + '/api/transcribe', headers=headers, files=files, timeout=300)
    except requests.exceptions.RequestException as e:
        print('request error', e)
        resp = None

if resp is None:
    print('No response')
else:
    print('status', resp.status_code)
    try:
        print('json:', resp.json())
    except Exception:
        print('text:', resp.text[:200])

# cleanup
print('Cleaning up...')
db.delete_user(user_id)
try:
    os.remove(wav_path)
except Exception:
    pass
