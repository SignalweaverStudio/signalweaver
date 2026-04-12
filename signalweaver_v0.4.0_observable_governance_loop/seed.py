"""
SignalWeaver seed script
Bootstraps a clean demo environment with anchors and profiles.
Run from the project root with the server already running:
    python seed.py
"""

import urllib.request
import urllib.error
import json

BASE_URL = "http://127.0.0.1:8000"


def post(path, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            return result
    except urllib.error.HTTPError as e:
        print(f"  ERROR {e.code}: {e.read().decode()}")
        return None


def get(path):
    req = urllib.request.Request(f"{BASE_URL}{path}", method="GET")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  ERROR {e.code}: {e.read().decode()}")
        return None


def get_or_create_profile(name, description):
    existing = get("/profiles/")
    if existing:
        for p in existing.get("items", []):
            if p["name"] == name:
                print(f"  Profile {p['id']}: {p['name']} (already exists)")
                return p
    return post("/profiles/", {"name": name, "description": description})


def check_server():
    try:
        result = get("/health")
        return result and result.get("status") == "ok"
    except Exception:
        return False


def main():
    print("SignalWeaver seed script")
    print("------------------------")

    # Check server is up
    print("\nChecking server...")
    if not check_server():
        print("  ERROR: Server not running at http://127.0.0.1:8000")
        print("  Start it with: python -m uvicorn app.main:app --reload")
        return
    print("  Server OK")

    # Seed anchors
    print("\nCreating anchors...")

    anchors = [
        {"level": 3, "statement": "Do not assist with unauthorized access to systems or property", "scope": "security"},
        {"level": 3, "statement": "Do not facilitate deception or manipulation of users", "scope": "integrity"},
        {"level": 2, "statement": "Avoid actions that could cause financial harm", "scope": "payments"},
        {"level": 1, "statement": "Do not permanently delete, destroy, or irreversibly remove data without confirmation", "scope": "global"},
    ]

    anchor_ids = {}
    for a in anchors:
        result = post("/anchors/", a)
        if result:
            anchor_ids[a["scope"]] = result["id"]
            print(f"  Anchor {result['id']} (L{result['level']}, {result['scope']}): {result['statement'][:60]}...")

    if len(anchor_ids) < len(anchors):
        print("\n  WARNING: Some anchors failed to create. Aborting profile setup.")
        return

    # Seed profiles
    print("\nCreating profiles...")

    security_profile = get_or_create_profile(
        "security", "Security and integrity boundary enforcement"
    )
    if security_profile:
        post(f"/profiles/{security_profile['id']}/anchors", {
            "anchor_ids": [anchor_ids["security"], anchor_ids["integrity"]]
        })
        print(f"    Assigned anchors: security, integrity")

    payments_profile = get_or_create_profile(
        "payments", "Financial transaction boundaries"
    )
    if payments_profile:
        post(f"/profiles/{payments_profile['id']}/anchors", {
            "anchor_ids": [anchor_ids["payments"], anchor_ids["global"]]
        })
        print(f"    Assigned anchors: payments, global")

    # Summary
    print("\nSeed complete.")
    print(f"  Anchors: {len(anchor_ids)}")
    print(f"  Profiles: 2")
    print(f"\nSwagger UI: {BASE_URL}/docs")
    print(f"Demo walkthrough: DEMO.md")


if __name__ == "__main__":
    main()