# SignalWeaver

**Your AI agents are making decisions. Can you prove they made the right ones?**

AI systems are approving refunds, granting access, triggering workflows,
and executing automated actions.

Most teams have no consistent way to enforce policy on those decisions —
or explain them after the fact.

When something goes wrong, *"the AI decided"* is not an acceptable answer.

SignalWeaver is a deterministic policy enforcement layer. It sits between your AI agent and the actions it takes, evaluates every request against your policy rules, and returns a decision: **proceed**, **gate**, or **refuse**. Every decision is logged with a replayable trace. Same input, same policy version, same output — every time.

---

## What it does

- **Policy enforcement** — human-written rules, checked before every action
- **Deterministic decisions** — same input always produces the same output
- **Replayable traces** — any past decision can be reconstructed exactly and audited later
- **No model dependency** — rules are plain text, not prompts. Model behaviour doesn't affect enforcement.
- **SignalWeaver does for AI decisions what firewalls do for network traffic.
---

## Quick example

You have an AI customer support agent that can approve refunds. Your policy: refunds above £10,000 need a human to sign off.

**1. Create the policy anchor:**

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/anchors" `
  -Method POST -ContentType "application/json" `
  -Body '{"level": 3, "statement": "Do not approve refunds above £10000 without manual review", "scope": "payments.refunds"}'
```

**2. AI proposes a £12,000 refund — evaluate it:**

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/gate/evaluate" `
  -Method POST -ContentType "application/json" `
  -Body '{"request_summary": "Approve refund of £12000 for customer", "arousal": "unknown", "dominance": "unknown"}'
```

Response:
```json
{
  "decision": "gate",
  "reason": "l3_anchor_conflict",
  "trace_id": 1,
  "interpretation": "This conflicts with a level-3 boundary (protected constraint).",
  "explanations": ["Anchor L3 (payments.refunds): triggered by refund amount above threshold"]
}
```

The refund is held for human review. The decision is logged.

**3. Later, prove it was handled correctly:**

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/gate/replay/1" -Method GET
```

```json
{
  "trace_id": 1,
  "same_decision": true,
  "same_reason": true,
  "anchor_drift": []
}
```

---

## Decision outcomes

| Decision | When |
|---|---|
| `proceed` | No policy conflicts detected |
| `gate` | Conflicts with a protected constraint — hold for human review |
| `refuse` | Multiple protected constraints violated — block entirely |

---

## Policy anchors

Anchors are your policy rules. Each one has:

- `level` (1–3) — how strictly it's enforced. Level 3 = hard gate or refuse.
- `statement` — the rule in plain language
- `scope` — domain tag (e.g. `payments.refunds`, `access.admin`, `global`)
- `active` — toggle on/off without deletion

Anchors are stored in the database and evaluated on every request. They're not prompts — model behaviour doesn't change how they're evaluated.

---

## Insight (decision analytics)

SignalWeaver can analyse historical decisions using the Insight endpoints.

These allow teams to understand:

• which rules trigger most often
• where human overrides occur
• whether policies drift over time
• which anchors are unused

This turns decision logs into operational intelligence rather than just an audit trail.

---
## Getting started

Requirements: Python 3.10+, Windows (PowerShell) or Linux/Mac

**1. Clone and set up:**

```powershell
git clone <repo-url>
cd signalweaver-fresh
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**2. Start the server:**

```powershell
.\run.ps1
```

Server runs at `http://localhost:8000`. Swagger UI at `http://localhost:8000/docs`.

**3. Run tests:**

```powershell
cd src
python -m pytest tests/ -v
```

---

## Governance modes

Run SignalWeaver in three modes:

| Mode | Behaviour |
|---|---|
| `shadow` | Evaluate and log everything — no blocking. See what would have been caught. |
| `soft` | Gate on policy-sensitive decisions, let the rest through. |
| `hard` | Full enforcement. Gate and refuse as defined. |

Most teams start in **shadow mode** for a week or two. You understand what the engine catches before turning on enforcement. Zero interference with existing workflows.

---

## API reference

**Anchors**

| Method | Endpoint | Description |
|---|---|---|
| POST | `/anchors/` | Create a policy anchor |
| GET | `/anchors/` | List active anchors |
| GET | `/anchors/{id}` | Get a specific anchor |
| POST | `/anchors/{id}/archive` | Deactivate an anchor |

**Gate**

| Method | Endpoint | Description |
|---|---|---|
| POST | `/gate/evaluate` | Evaluate a request against policy |
| POST | `/gate/reframe` | Re-evaluate a gated request with new intent |
| GET | `/gate/replay/{trace_id}` | Replay a past decision and check for drift |
| GET | `/gate/logs` | List decision logs |

**Profiles**

| Method | Endpoint | Description |
|---|---|---|
| POST | `/profiles/` | Create a named policy profile |
| GET | `/profiles/` | List profiles |
| POST | `/profiles/{id}/anchors` | Assign anchors to a profile |

---

## Optional: embedding matcher

By default, SignalWeaver uses keyword-based conflict detection. For semantic matching:

```powershell
$env:SW_MATCHER = "embedding"
.\run.ps1
```

Requires `sentence-transformers` and `scikit-learn`:

```powershell
pip install sentence-transformers scikit-learn
```

---

## Use cases

- AI customer support agents approving refunds or credits
- AI systems granting or denying access to resources
- AI agents executing automated workflows on behalf of users
- Any automated decision that touches money, access, or compliance

---

## Project status

Working backend prototype. Core engine is operational: policy evaluation, decision traces, replay, and drift detection all functional. No UI — interaction is via API.

**Not yet implemented:** authentication, multi-tenancy, production hardening.

This is intentional. The engine works. The productisation layer is in progress. If you're running AI agents in production and want to evaluate SignalWeaver as a governance layer before it's fully hardened, that's exactly the kind of conversation we're looking for.

→ **signalweaver.studio@gmail.com**

---

## License

Experimental. Not production hardened.

Commercial use requires OEM licensing. Contact: licensing@signalweaver.io

See `DEMO.md` for a full walkthrough including reframing, profile scoping, and drift detection.
