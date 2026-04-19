SignalWeaver
A governance layer that sits between AI and action.

SignalWeaver evaluates requests against declared policy, produces a deterministic decision, and records a replayable trace for audit. It doesn't classify content. It doesn't align models. It governs what AI agents are allowed to do.

The problem
AI agents are increasingly allowed to trigger real-world actions — approving refunds, executing trades, granting access, deleting data, sending emails. Most teams have no deterministic policy layer governing those decisions. When something goes wrong, there's no audit trail, no explanation, and no way to prove what happened.

SignalWeaver provides that layer.

What it does
Deterministic decisions — same input, same policy, always the same output. No model non-determinism in the enforcement path.
Three enforcement tiers — proceed, gate (hold for review), refuse (hard block). Not binary. Not pass/fail. Governance.
Replayable traces — every decision is logged with a full anchor snapshot. Re-run any past decision to detect policy drift.
Explainable outcomes — every gate names the anchor that triggered, the phrases that matched, and the reasoning path. No black boxes.
Policy profiles — different contexts, different rules. A payments profile gates financial actions. A security profile gates access. Same engine.
Insight analytics — which rules trigger most, where overrides cluster, which anchors are dead, counterfactual simulation of policy changes against real decision history.
Governance spectrum — run in shadow mode (observe, never block), soft mode (gate with override), or hard mode (full enforcement). Start in shadow. Turn it up when you're ready.
How it works
AI Agent proposes action
↓
SignalWeaver /gate/evaluate
↓
Load active policy anchors
↓
Detect conflicts (keyword or semantic matching)
↓
Run deterministic decision logic
↓
Apply enforcement mode (shadow / soft / hard)
↓
Return decision + explanation + trace ID
↓
Decision logged with full anchor snapshot

text


Every decision produces:
- A clear outcome: `proceed`, `gate`, or `refuse`
- A human-readable explanation of what triggered and why
- A trace ID for audit and replay
- Ethos references linking the decision to declared system invariants

---

## Quick example

**1. Create a policy anchor:**

```bash
curl -X POST http://localhost:8000/anchors/ \
  -H "Authorization: Bearer <api-key>" \
  -H "Content-Type: application/json" \
  -d '{"level": 3, "statement": "Do not approve refunds above £10000 without manual review", "scope": "payments.refunds"}'
2. AI proposes a £12,000 refund — evaluate it:

bash

curl -X POST http://localhost:8000/gate/evaluate \
  -H "Authorization: Bearer <api-key>" \
  -H "Content-Type: application/json" \
  -d '{"request_summary": "Approve refund of £12000 for customer", "arousal": "unknown", "dominance": "unknown"}'
Response:

json

{
  "decision": "gate",
  "reason": "l3_anchor_conflict",
  "trace_id": 1,
  "interpretation": "This conflicts with a level-3 boundary (protected constraint).",
  "explanations": ["Anchor L3 (payments.refunds): triggered by refund amount above threshold"],
  "next_actions": ["reframe", "view_conflicts", "cancel"],
  "ethos_refs": ["Explainability over opacity", "Reversibility", "Slow is a feature"]
}
The refund is held. The decision is logged. The reasoning is transparent.

3. Prove it was handled correctly:

bash

curl http://localhost:8000/gate/replay/1 \
  -H "Authorization: Bearer <api-key>"
json

{
  "trace_id": 1,
  "same_decision": true,
  "same_reason": true,
  "anchor_drift": []
}
Decision outcomes
Decision
When
User path
proceed	No policy conflicts detected	Continue normally
gate	Conflicts with a protected constraint	Reframe intent, acknowledge risk, or cancel
refuse	Multiple protected constraints violated simultaneously	No reframing path — action blocked

Policy anchors
Anchors are your policy rules. Each one has:

level (1–3) — how strictly it's enforced
Level 3: protected constraint — gate or refuse
Level 2: policy constraint — soft gate with override option
Level 1: advisory — proceeds with warning
statement — the rule in plain language
scope — domain tag (e.g. payments.refunds, access.admin, global)
active — toggle on/off without deletion
Anchors are stored in the database and evaluated on every request. They're not prompts — model behaviour doesn't change how they're evaluated.

Key capabilities
Replay and drift detection. Every decision snapshots the full policy state at evaluation time. Replay any trace to detect if anchor hashes changed, active flags flipped, or new anchors were added since the original decision. Silent policy drift is surfaced.

Counterfactual policy testing. Simulate how policy changes would have affected historical decisions before deploying them. "What would have happened if we tightened this rule?" — answered against real decision data, not guesswork.

Multi-tenant isolation. API key authentication with tenant-scoped anchors and profiles. Each tenant's policy context is isolated.

Embedding matcher (optional). Switch from keyword matching to semantic similarity with SW_MATCHER=embedding. Uses sentence-transformers for vector-based conflict detection. Falls back to keyword matching automatically if no semantic matches are found.

Insight analytics. Decision volume, gate/refuse rates, override rates per anchor, dead anchor detection, and participation tracking. Turns decision logs into operational intelligence.

Governance modes
Mode
Behaviour
shadow	Evaluate and log everything — never block. See what would have been caught.
soft	Gate on policy-sensitive decisions, allow override with recorded acknowledgement.
hard	Full enforcement. Gate and refuse as defined.

Most teams start in shadow mode for a week or two. Understand what the engine catches before turning on enforcement. Zero interference with existing workflows.

API reference
Gate

Method
Endpoint
Description
POST	/gate/evaluate	Evaluate a request against policy
POST	/gate/reframe	Re-evaluate a gated request with new intent
GET	/gate/replay/{trace_id}	Replay a past decision and check for drift
GET	/gate/logs	List decision logs with filters

Anchors

Method
Endpoint
Description
POST	/anchors/	Create a policy anchor
GET	/anchors/	List active anchors
GET	/anchors/{id}	Get a specific anchor
POST	/anchors/{id}/archive	Deactivate an anchor

Profiles

Method
Endpoint
Description
POST	/profiles/	Create a named policy profile
GET	/profiles/	List profiles
PATCH	/profiles/{id}	Update a profile
DELETE	/profiles/{id}	Delete a profile
PUT	/profiles/{id}/anchors	Assign anchors to a profile

Tenants

Method
Endpoint
Description
POST	/tenants/	Create a tenant (returns API key)
GET	/tenants/	List tenants

Insight

Method
Endpoint
Description
GET	/reports/shadow-summary	Decision analytics summary

Getting started
Requirements: Python 3.10+, Docker (optional)

1. Clone and set up:

bash

git clone https://github.com/SignalweaverStudio/signalweaver.git
cd signalweaver
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
2. Start the server:

bash

cd src
uvicorn app.main:app --reload
Server runs at http://localhost:8000. Swagger UI at http://localhost:8000/docs.

3. Docker:

bash

docker-compose up
4. Run tests:

bash

cd src
python -m pytest tests/ -v
Architecture
Core: FastAPI + SQLAlchemy + SQLite
Decision engine: Pure Python, deterministic, no model dependency
Matching: Keyword (default) or sentence-transformers embedding (optional)
Auth: Bearer token with tenant-scoped API keys
Storage: SQLite (dev), portable to PostgreSQL
Design invariants
SignalWeaver operates under 10 declared invariants that constrain every feature. These aren't aspirational — they're enforced in code.

Agency first — the system may refuse, gate, or invite reconsideration. It must not coerce.
Reversibility — every gate leaves the user in a stable state.
Truthful memory — decisions resist revisionism. If a decision can't be justified on replay, it shouldn't have been made.
Explainability over opacity — every gate names what triggered it and why.
Refusal is a valid act — gates and refusals are treated with the same seriousness as approvals.
Consent over silence — if a boundary is crossed, the crossing is explicit and on record.
Anti-coercion — a gate is information, not punishment.
Slow is a feature — friction is appropriate when stakes are high.
Minimal necessary intervention — do the smallest safe thing.
Auditability — the system must be inspectable at any point.
See ETHOS.md for the full text.

Use cases
AI customer support agents approving refunds or credits
AI agents executing tool calls (file deletion, payments, shell commands)
AI systems granting or denying access to resources
Automated workflows that touch money, access, or compliance
Any AI decision that needs to be explainable to an auditor
Project status
SignalWeaver is under active development. The core decision engine, replay system, insight analytics, and multi-tenant auth are operational.

The system is governance-ready but not yet production-hardened. If you're running AI agents in production and want to evaluate SignalWeaver as a governance layer, that's exactly the conversation we're looking for.

Contact: signalweaver.studio@gmail.com

License
Experimental. Not production hardened.

Commercial use requires OEM licensing. Contact: licensing@signalweaver.io

See LICENSING.md for details.
