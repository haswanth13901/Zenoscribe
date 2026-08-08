import os
import sys
import time
sys.path.insert(0, os.getcwd())
import db, auth
import requests

BASE = 'http://127.0.0.1:8000'
user = 'tc06_user'
password = 'CorrectPass123!'

print('Creating test user...')
user_id = db.create_user(user, auth.hash_password(password), full_name='TC06 User')
print('user_id', user_id)

# Ensure no prior failed logins remain for this (username, ip)
client_ip = '127.0.0.1'
db.clear_failed_logins(user, client_ip)

# Submit LOGIN_ATTEMPT_LIMIT wrong attempts and expect 401
from config import LOGIN_ATTEMPT_LIMIT
for i in range(1, LOGIN_ATTEMPT_LIMIT + 1):
    r = requests.post(BASE + '/api/login', json={'username': user, 'password': 'WrongPass'})
    print(f'attempt {i} status', r.status_code)
    assert r.status_code == 401, f'Attempt {i} expected 401, got {r.status_code} {r.text}'

# Next attempt should be blocked with 429
r = requests.post(BASE + '/api/login', json={'username': user, 'password': 'WrongPass'})
print('blocked attempt status', r.status_code, r.text)
assert r.status_code == 429, f'Expected 429 on blocked attempt, got {r.status_code} {r.text}'

print('TC-06 passed: brute-force throttling works')

# Cleanup
try:
    db.clear_failed_logins(user, client_ip)
    db.delete_user(user_id)
except Exception:
    pass
