"""Manual diagnostic: eyeball request latency against a running dev server.

Not a pytest test - no assertions, just prints min/avg/max response time.
Start the server yourself first, then run this:

    python -m uvicorn voice_transcriber.server:app --port 8000
    python scripts/latency_check.py
"""
import time
import urllib.request

urls = ['http://127.0.0.1:8000/']
for u in urls:
    times = []
    for i in range(5):
        t0 = time.time()
        with urllib.request.urlopen(u) as r:
            r.read()
        times.append(time.time() - t0)
    print(u, 'min', min(times), 'avg', sum(times) / len(times), 'max', max(times))
