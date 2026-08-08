import requests, tempfile, os, time, sys
sys.path.insert(0, os.getcwd())
import db, auth
BASE='http://127.0.0.1:8000'
user='tc07_int_user'
password='Tc07Pass!'
print('Creating user...')
uid=db.create_user(user, auth.hash_password(password), full_name='TC07 Int User')
print('user id',uid)
r=requests.post(BASE+'/api/login', json={'username':user,'password':password})
print('login status', r.status_code)
if r.status_code!=200:
    print(r.text)
    raise SystemExit(1)

token=r.json().get('token')
headers={'Authorization':f'Bearer {token}'}

p=os.path.join(tempfile.gettempdir(),'tc07_integ.wav')
import wave
with wave.open(p,'wb') as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)
    wf.writeframes((b'\x00\x00')*16000)

print('Uploading wav...')
try:
    files={'file':('tc07.wav', open(p,'rb'),'audio/wav')}
    resp=requests.post(BASE+'/api/transcribe', headers=headers, files=files, timeout=20)
    print('response status',resp.status_code)
    try:
        print('response json', resp.json())
    except Exception:
        print('response text', resp.text[:500])
except requests.exceptions.RequestException as e:
    print('request exception', type(e), e)
finally:
    try: os.remove(p)
    except: pass
