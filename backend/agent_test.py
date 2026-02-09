import os
import subprocess
import sys
import time

import httpx

BASE_URL = "http://127.0.0.1:8000"


def wait_for_server(timeout_seconds: float = 15.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE_URL}/health", timeout=0.5)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def main() -> int:
    env = os.environ.copy()
    env["SIGNALWEAVER_DB"] = str((os.path.join(os.getcwd(), "signalweaver_test.db")))


    cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8000"]

    proc = subprocess.Popen(
    cmd,
    cwd="src",
    stdout=None,            # show logs in the terminal
    stderr=subprocess.STDOUT,
    text=True,
    env=env,
)


    try:
        if not wait_for_server():
            print("❌ Server did not become ready in time.")
            return 1

        result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=".")
        return result.returncode

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
