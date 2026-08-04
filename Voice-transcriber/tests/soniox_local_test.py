import sys, os, tempfile
sys.path.insert(0, os.getcwd())
import soniox_client as sx
p = os.path.join(tempfile.gettempdir(),'ci_transcribe_local.wav')
with open(p,'wb') as f:
    f.write(b'RIFF....WAVEfmt ')
print('calling transcribe_file on', p)
try:
    turns = sx.transcribe_file(p, poll_interval=1, timeout=30)
    print('returned', turns)
except Exception as e:
    import traceback
    traceback.print_exc()
    print('Exception:', type(e), e)
finally:
    try:
        os.remove(p)
    except Exception:
        pass
