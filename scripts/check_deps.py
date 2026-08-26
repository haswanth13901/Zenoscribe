"""Bootstrap helper: makes sure Postgres and Redis are actually reachable,
instead of just telling the developer they need to be (see bootstrap.sh /
bootstrap.ps1). Both scripts call this as their last step.

If Docker is available, proactively starts the `db`/`redis` compose
services - `docker compose up -d` is idempotent, so this is safe to run
every time, whether they're already up or not. Then verifies both are
actually accepting TCP connections before declaring success, since a
container can be "Started" well before Postgres/Redis inside it is ready
for connections.

Deliberately never raises the bootstrap script's own exit code - this is
advisory (tells you what's wrong and how to fix it), not a hard gate.
"""
import os
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_dotenv_value(key: str) -> str | None:
    env_path = os.path.join(ROOT, ".env")
    if not os.path.exists(env_path):
        return None
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip()
    return None


def resolve(key: str, default: str) -> str:
    return os.environ.get(key) or load_dotenv_value(key) or default


def check(url: str, default_port: int, name: str, timeout=2.0) -> bool:
    parsed = urlparse(url)
    host, port = parsed.hostname or "localhost", parsed.port or default_port
    try:
        with socket.create_connection((host, port), timeout=timeout):
            print(f"[bootstrap] {name} reachable at {host}:{port}")
            return True
    except OSError:
        print(f"[bootstrap] {name} NOT reachable at {host}:{port}")
        return False


def try_start_via_docker():
    if shutil.which("docker") is None:
        return False
    print("[bootstrap] Docker found - starting db/redis via `docker compose up -d db redis`")
    try:
        subprocess.run(
            ["docker", "compose", "up", "-d", "db", "redis"],
            cwd=ROOT, check=True, capture_output=True, text=True, timeout=120,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"[bootstrap] Could not start db/redis via docker compose: {exc}")
        return False


def main():
    db_url = resolve("DATABASE_URL", "postgresql://localhost:5432")
    redis_url = resolve("REDIS_URL", "redis://localhost:6379")

    db_ok = check(db_url, 5432, "Postgres")
    redis_ok = check(redis_url, 6379, "Redis")

    if not (db_ok and redis_ok) and try_start_via_docker():
        print("[bootstrap] Waiting for containers to accept connections")
        for _ in range(30):
            db_ok = check(db_url, 5432, "Postgres", timeout=1.0)
            redis_ok = check(redis_url, 6379, "Redis", timeout=1.0)
            if db_ok and redis_ok:
                break
            time.sleep(2)

    if db_ok and redis_ok:
        print("[bootstrap] Postgres and Redis are both reachable - the app is ready to run.")
    else:
        print(
            "[bootstrap] WARNING: app will fail to start (or every request will 503) "
            "without both reachable. Run 'docker compose up -d db redis', or point "
            "DATABASE_URL/REDIS_URL in .env at instances you already have."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
