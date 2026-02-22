"""
seed_anchors.py — Seed SignalWeaver with demo truth anchors for the MCP demo.
Run this once before running demo.py.
Usage:
    python seed_anchors.py
"""
import asyncio
import httpx
import os

SW_BASE_URL = os.getenv("SW_BASE_URL", "http://localhost:8000")
SW_API_KEY  = os.getenv("SW_API_KEY", "")

def _headers():
    h = {"Content-Type": "application/json"}
    if SW_API_KEY:
        h["X-API-Key"] = SW_API_KEY
    return h

ANCHORS = [
    {
        "level": 3,
        "statement": "Do not DELETE or OVERWRITE data without explicit user confirmation",
        "scope": "filesystem",
    },
    {
        "level": 3,
        "statement": "Do not send emails without explicit user confirmation",
        "scope": "communications",
    },
    {
        "level": 3,
        "statement": "Do not execute shell commands that delete or overwrite data",
        "scope": "system",
    },
    # Level 2 — warnings (gate fires, lower severity)
    {
        "level": 3,
        "statement": "Do not process payments above £100 without explicit user review",
        "scope": "payments",
    },
    {
        "level": 2,
        "statement": "Do not access external accounts or transfer funds without confirmation",
        "scope": "payments",
    },
    # Level 1 — soft nudges (proceed with warning)
    {
        "level": 1,
        "statement": "Prefer read-only operations when write is not explicitly required",
        "scope": "global",
    },
]

DEMO_SCOPES = {"filesystem", "communications", "system", "payments", "payments.refunds", "global"}

# Statements we consider part of the demo set (old + new variants)
DEMO_STATEMENTS = {
    # filesystem
    "Do not delete files or data without explicit user confirmation",
    "Do not DELETE or OVERWRITE data without explicit user confirmation",

    # comms
    "Do not send emails without explicit user confirmation",

    # system
    "Do not execute shell commands that delete or overwrite data",

    # payments (old/new)
    "Do not process payments above £100 without user review",
    "Do not process payments above £100 without explicit user review",
    "Do not process payments above 100 GBP without explicit user review",

    # payments generic
    "Do not access external accounts or transfer funds without confirmation",

    # global nudge
    "Prefer read-only operations when write is not explicitly required",
}

async def main():
    print(f"Seeding anchors into SignalWeaver at {SW_BASE_URL}\n")
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        # Health check
        try:
            r = await client.get(f"{SW_BASE_URL}/health")
            print(f"Backend: {r.json()}\n")
        except Exception as e:
            print(f"⚠️  Cannot reach {SW_BASE_URL}: {e}")
            return

        # Archive previous demo anchors to avoid duplicates
        try:
            r = await client.get(
                f"{SW_BASE_URL}/anchors/",
                params={"active_only": "false"},
                headers=_headers(),
            )
            r.raise_for_status()
            existing = r.json()

            to_archive = [
                a for a in existing
                if a.get("active") is True
                and (a.get("scope") in DEMO_SCOPES)
                and (a.get("statement") in DEMO_STATEMENTS)
            ]

            if to_archive:
                print(f"Archiving {len(to_archive)} previous demo anchor(s)…\n")
            for a in to_archive:
                anchor_id = a["id"]
                stmt = a["statement"]
                scope = a.get("scope")
                ar = await client.post(
                    f"{SW_BASE_URL}/anchors/{anchor_id}/archive",
                    headers=_headers(),
                )
                ar.raise_for_status()
                print(f"  🗄️  archived [{scope}] — {stmt[:70]}…")

            if to_archive:
                print("")
        except Exception as e:
            print(f"⚠️  Could not archive previous demo anchors: {e}\n")

        for anchor in ANCHORS:
            r = await client.post(
                f"{SW_BASE_URL}/anchors/",
                headers=_headers(),
                json=anchor,
            )
            if r.status_code in (200, 201):
                data = r.json()
                print(f"  ✅ L{anchor['level']} [{anchor['scope']}] — {anchor['statement'][:60]}...")
            elif r.status_code == 409:
                print(f"  ℹ️  Already exists: {anchor['statement'][:60]}...")
            else:
                print(f"  ❌ Failed ({r.status_code}): {r.text}")

    print("\nDone. Run demo.py to see the gate in action.")

if __name__ == "__main__":
    asyncio.run(main())