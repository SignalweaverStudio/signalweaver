"""
demo.py — SignalWeaver MCP Gate Demo

Simulates an LLM making tool calls that pass through SignalWeaver.
Runs without a real LLM — useful for showing the gate in action.

Usage:
    python demo.py

Requirements:
    - SignalWeaver running at http://localhost:8000
    - Some truth anchors seeded (run seed_anchors.py first)
"""

import asyncio
import httpx
import json
import os

SW_BASE_URL = os.getenv("SW_BASE_URL", "http://localhost:8000")
SW_API_KEY  = os.getenv("SW_API_KEY", "")

DIVIDER = "─" * 60


def _headers():
    h = {"Content-Type": "application/json"}
    if SW_API_KEY:
        h["X-API-Key"] = SW_API_KEY
    return h


async def gate(summary: str, arousal: str = "unknown", dominance: str = "unknown") -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{SW_BASE_URL}/gate/evaluate",
            headers=_headers(),
            json={"request_summary": summary, "arousal": arousal, "dominance": dominance},
        )
        r.raise_for_status()
        return r.json()


def print_result(tool: str, args: dict, result: dict):
    decision = result["decision"].upper()
    icon = "✅" if decision == "PROCEED" else "⛔"
    print(f"\n{DIVIDER}")
    print(f"{icon}  [{decision}]  {tool}({', '.join(f'{k}={v!r}' for k,v in args.items())})")
    print(f"   Reason      : {result.get('reason', '')}")
    print(f"   Interpret   : {result.get('interpretation', '')}")
    if result.get("suggestion"):
        print(f"   Suggestion  : {result['suggestion']}")
    if result.get("explanations"):
        print(f"   Conflicts   :")
        for e in result["explanations"]:
            print(f"     • {e}")
    if result.get("next_actions"):
        print(f"   Next actions: {', '.join(result['next_actions'])}")
    print(f"   Audit       : log_id={result.get('log_id')}  trace_id={result.get('trace_id')}")
    print(f"   Replay      : GET {SW_BASE_URL}/gate/replay/{result.get('trace_id')}")


# ── Demo scenarios ─────────────────────────────────────────────────────────────

SCENARIOS = [
    {
        "label": "Safe read — should PROCEED",
        "tool": "read_file",
        "args": {"path": "/home/nic/notes.txt"},
        "summary": "tool call: read_file(path='/home/nic/notes.txt') READ_ONLY",
        "arousal": "low",
        "dominance": "high",
    },
    {
        "label": "Delete file — should GATE (destructive action)",
        "tool": "delete_file",
        "args": {"path": "/var/data/users.db"},
        "summary": "tool call: delete_file(path='/var/data/users.db') permanently delete file",
        "arousal": "low",
        "dominance": "high",
    },
    {
        "label": "Send email without confirmation — should GATE",
        "tool": "send_email",
        "args": {"to": "ceo@company.com", "subject": "Resignation", "body": "I quit."},
        "summary": "tool call: send_email(to='ceo@company.com', subject='Resignation') send email without user confirmation",
        "arousal": "high",
        "dominance": "low",
    },
    {
        "label": "Large payment — should GATE",
        "tool": "process_payment",
        "args": {"amount": 5000, "to": "external-account-99"},
        "summary": "tool call: process_payment(amount=5000, to='external-account-99') payment £5000 ABOVE £100 without explicit user review",
        "arousal": "med",
        "dominance": "med",
    },
    {
        "label": "Shell command — should GATE (high risk)",
        "tool": "run_shell_command",
        "args": {"command": "rm -rf /tmp/cache"},
        "summary": "tool call: run_shell_command(command='rm -rf /tmp/cache') execute shell delete",
        "arousal": "low",
        "dominance": "high",
    },
]


async def main():
    print("SignalWeaver MCP Gate — Demo")
    print(f"Backend: {SW_BASE_URL}")
    print(DIVIDER)

    # Health check
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{SW_BASE_URL}/health")
            print(f"Backend status: {r.json()}")
    except Exception as e:
        print(f"⚠️  Cannot reach SignalWeaver at {SW_BASE_URL}: {e}")
        print("   Start the backend first: uvicorn app.main:app --reload")
        return

    # Run scenarios
    for scenario in SCENARIOS:
        print(f"\n>>> {scenario['label']}")
        result = await gate(
            scenario["summary"],
            arousal=scenario.get("arousal", "unknown"),
            dominance=scenario.get("dominance", "unknown"),
        )
        print_result(scenario["tool"], scenario["args"], result)

    print(f"\n{DIVIDER}")
    print("Demo complete. Full log: GET /gate/logs")
    print(f"Swagger UI: {SW_BASE_URL}/docs")


if __name__ == "__main__":
    asyncio.run(main())