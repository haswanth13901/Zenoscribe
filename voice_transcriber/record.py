import threading
import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wav

SR = 16000


def record(out="conversation.wav"):
    print("Recording... press Enter to stop.")
    chunks, stop = [], threading.Event()
    threading.Thread(target=lambda: (input(), stop.set()), daemon=True).start()

    with sd.InputStream(samplerate=SR, channels=1, dtype="int16") as s:
        while not stop.is_set():
            data, _ = s.read(1024)
            chunks.append(data.copy())

    audio = np.concatenate(chunks)
    wav.write(out, SR, audio)
    print(f"Saved {out} ({len(audio) / SR:.1f}s)")
    return out


if __name__ == "__main__":
    record()
