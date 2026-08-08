import sys, os, tempfile, wave
sys.path.insert(0, os.getcwd())
import soniox_client as sx

# Create a small valid WAV (1s silence, 16kHz mono, 16-bit) so Soniox accepts it.
p = os.path.join(tempfile.gettempdir(), 'ci_transcribe_local.wav')
with wave.open(p, 'wb') as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)  # 16-bit
    wf.setframerate(16000)
    silence = (b'\x00\x00') * 16000  # 1 second of silence
    wf.writeframes(silence)

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
