# SignalWeaver

**A governance layer for AI systems that make real-world decisions.**

SignalWeaver sits between an AI agent and the actions it wants to take. When your AI proposes something — approving a refund, granting access, triggering a workflow — SignalWeaver checks it against your policy rules and returns a deterministic decision: **proceed**, **gate**, or **refuse**. Every decision is logged with a trace that can be replayed later to prove consistency.

---

## The problem it solves

AI systems are making decisions — approving things, denying things, running automations. Most teams have no consistent way to enforce policy on those decisions or explain them after the fact.

When something goes wrong, "the AI decided" is not an acceptable answer.

SignalWeaver gives you a control layer with:

- **Policy enforcement** — human-written rules, checked before every action
- **Deterministic decisions** — same input always produces the same output
- **Replayable traces** — every decision can be reconstructed and audited later
- **No model dependency** — rules are plain text, not prompts

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

**Response:**
```json
{
  "decision": "gate",
  "reason": "l3_anchor_conflict",
  "trace_id": 1,
  "interpretation": "This conflicts with a level-3 boundary (protected constraint).",
  "explanations": ["Anchor L3 (payments.refunds): triggered by refund amount above threshold"]
}
```

The refund is held for human review. The decision is logged. Later, you can prove it was handled correctly:

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
|----------|------|
| `proceed` | No policy conflicts detected |
| `gate` | Conflicts with a protected constraint — hold for review |
| `refuse` | Multiple protected constraints violated — block entirely |

---

## Policy anchors

Anchors are your policy rules. Each one has:

- `level` (1–3) — how strictly it's enforced (3 = hard gate/refuse)
- `statement` — the rule in plain language
- `scope` — domain tag (e.g. `payments.refunds`, `access.admin`, `global`)
- `active` — can be toggled on/off without deletion

Anchors are stored in the database and evaluated on every request. They're not prompts — they don't change based on model behaviour.

---

## Getting started

**Requirements:** Python 3.10+, Windows (PowerShell) or Linux/Mac

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

## API reference

### Anchors
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/anchors/` | Create a policy anchor |
| `GET` | `/anchors/` | List active anchors |
| `GET` | `/anchors/{id}` | Get a specific anchor |
| `POST` | `/anchors/{id}/archive` | Deactivate an anchor |

### Gate
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/gate/evaluate` | Evaluate a request against policy |
| `POST` | `/gate/reframe` | Re-evaluate a gated request with new intent |
| `GET` | `/gate/replay/{trace_id}` | Replay a past decision and check for drift |
| `GET` | `/gate/logs` | List decision logs |

### Profiles
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/profiles/` | Create a named policy profile |
| `GET` | `/profiles/` | List profiles |
| `POST` | `/profiles/{id}/anchors` | Assign anchors to a profile |

---

## Governance spectrum

Run SignalWeaver in three modes:

- **Shadow** (`SW_MODE=shadow`) — evaluate and log everything, but don't block. See what would have been caught.
- **Soft** — gate on policy-sensitive decisions, let the rest through.
- **Hard** — full enforcement. Gate and refuse as defined.

Most teams start in shadow mode for a week to understand what the engine catches before turning on enforcement.

---

## Optional: embedding matcher

By default, SignalWeaver uses keyword-based conflict detection. For semantic matching:

```powershell
$env:SW_MATCHER = "embedding"
.\run.ps1
```

Requires `sentence-transformers` and `scikit-learn`. Install with:
```powershell
pip install sentence-transformers scikit-learn
```

---

## Project status

Working backend prototype. Core engine is functional: policy evaluation, decision traces, replay, and drift detection are all operational. No UI — interaction is via API.

Active focus: stability, test coverage, and demonstrability.

---

## Use cases

- AI customer support approving refunds or credits
- AI systems granting or denying access
- AI agents executing automated workflows
- Any automated decision that needs policy enforcement and an audit trail

---

## License

Experimental — not production hardened.
Commercial use requires OEM licensing. Contact: licensing@signalweaver.io

---

*See [DEMO.md](./DEMO.md) for a full walkthrough including reframing, profile scoping, and drift detection.*
