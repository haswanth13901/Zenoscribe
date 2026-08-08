import os
import sys
import tempfile
import time
sys.path.insert(0, os.getcwd())
import soniox_client as sx

# Simulate Soniox being unreachable by pointing REST to a non-routable address
original_rest = sx.REST
original_get_api_key = sx.get_api_key
original_upload_timeout = getattr(sx, 'UPLOAD_TIMEOUT', None)
sx.get_api_key = lambda: 'dummykey'
sx.UPLOAD_TIMEOUT = 3
sx.REST = 'http://10.255.255.1'

# Create a valid WAV to upload
p = os.path.join(tempfile.gettempdir(), 'tc07_ci.wav')
import wave
with wave.open(p, 'wb') as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)
    wf.writeframes((b'\x00\x00') * 16000)

print('calling transcribe_file with REST set to non-routable host')
start = time.time()
try:
    try:
        # Set a small overall timeout so test runs fast
        sx.transcribe_file(p, poll_interval=1.0, timeout=5)
        print('ERROR: expected timeout or failure but transcribe_file returned')
    except TimeoutError as te:
        print('Got TimeoutError as expected:', te)
    except RuntimeError as re:
        print('Got RuntimeError (network failure) as expected:', re)
    except Exception as e:
        print('Got unexpected exception type:', type(e), e)
finally:
    sx.REST = original_rest
    sx.get_api_key = original_get_api_key
    if original_upload_timeout is not None:
        sx.UPLOAD_TIMEOUT = original_upload_timeout
    try:
        os.remove(p)
    except Exception:
        pass

print('Elapsed', time.time() - start)
