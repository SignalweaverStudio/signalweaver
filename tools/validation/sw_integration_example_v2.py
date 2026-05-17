#!/usr/bin/env python3
"""
SignalWeaver Integration Example — 30 lines or fewer.
Drop this into your AI agent before it executes any action.
"""
import json, os
from urllib.request import Request, urlopen

SW_URL = os.getenv("SW_URL", "http://127.0.0.1:8000/gate/evaluate")
SW_KEY = os.getenv("SIGNALWEAVER_API_KEY", "")

def govern(action: str, arousal: str = "unknown", dominance: str = "unknown") -> dict:
    """Evaluate a proposed AI action through SignalWeaver."""
    headers = {"Content-Type": "application/json"}
    if SW_KEY: headers["X-API-Key"] = SW_KEY
    body = json.dumps({"request_summary": action, "arousal": arousal, "dominance": dominance}).encode()
    with urlopen(Request(SW_URL, data=body, headers=headers), timeout=5) as r:
        return json.loads(r.read())

# ── Your AI agent wants to do something ──
proposed_action = "Process a £12,000 refund to account ending 4491"

# ── Ask SignalWeaver before executing ──
result = govern(proposed_action, arousal="high", dominance="low")
decision = result["decision"]

# ── Branch on the decision ──
if decision == "proceed":
    print(f"PROCEED: {proposed_action}")       # execute the action
elif decision == "gate":
    print(f"GATE: Escalating to human. Reason: {result['reason']}")  # hold for review
else:
    print(f"REFUSE: {result['reason']}")       # block entirely
