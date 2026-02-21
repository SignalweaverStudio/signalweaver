import os
import subprocess
import sys
import time

import httpx

BASE_URL = "http://127.0.0.1:8000"


def wait_for_server(timeout_seconds: float = 10.0) -> None:
    deadline = time.time() + timeout_seconds
    last_err = None
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE_URL}/health", timeout=0.5)
            if r.status_code == 200:
                return
        except Exception as e:
            last_err = e
        time.sleep(0.2)
    raise RuntimeError(f"Server did not start in time. Last error: {last_err}")


def start_server(env):
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app"]
    proc = subprocess.Popen(
        cmd,
        cwd="src",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    wait_for_server()
    return proc


def stop_server(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    env = dict(os.environ)
    env["SIGNALWEAVER_DB"] = "signalweaver_test.db"

    # Start #1
    p1 = start_server(env)
    try:
        payload = {"level": 1, "statement": "persist check anchor"}
        r = httpx.post(f"{BASE_URL}/anchors/", json=payload, timeout=2)
        if r.status_code != 200:
            print("❌ Create failed:", r.status_code, r.text)
            return 1
        created = r.json()
        anchor_id = created["id"]
    finally:
        stop_server(p1)

    # Start #2
    p2 = start_server(env)
    try:
        r2 = httpx.get(f"{BASE_URL}/anchors/", timeout=2)
        if r2.status_code != 200:
            print("❌ List failed:", r2.status_code, r2.text)
            return 1

        items = r2.json()
        if not any(a.get("id") == anchor_id for a in items):
            print("❌ Anchor did not persist across restart.")
            return 1

        print("✅ Persistence test passed.")
        return 0
    finally:
        stop_server(p2)


if __name__ == "__main__":
    raise SystemExit(main())
