# SignalWeaver — Live Demo Walkthrough

**What this document is:** A complete record of SignalWeaver's core decision loop running live, with explanation of what each step means and why it matters.

---

## The Problem This Solves

Most AI systems make decisions you can't inspect.

When a model refuses a request, or allows one it shouldn't, there's no audit trail. No explanation of which rule triggered. No way to replay the decision after policy changes. No way to prove the system behaved consistently.

SignalWeaver is a policy gate that sits between user intent and system action. Every decision is:

- **Deterministic** — the same input against the same policy always produces the same output
- **Explainable** — every gate names the anchor that triggered and why
- **Traceable** — every evaluation is logged with a trace ID
- **Replayable** — any past decision can be re-run to detect policy drift
- **Scoped** — different policy profiles produce different decisions from the same engine

---

## Setup

Four Truth Anchors were seeded into the system:

| ID | Level | Scope | Statement |
|----|-------|-------|-----------|
| 6 | 3 | security | Do not assist with unauthorized access to systems or property |
| 7 | 3 | integrity | Do not facilitate deception or manipulation of users |
| 8 | 2 | payments | Avoid actions that could cause financial harm |
| 10 | 1 | global | Do not permanently delete, destroy, or irreversibly remove data without confirmation |

**Level meanings:**
- Level 3 — protected constraint, hard gate, no pass-through
- Level 2 — policy constraint, soft gate, user can acknowledge and proceed
- Level 1 — advisory, proceeds but flagged in the response

Two policy profiles were created and assigned anchors:

| Profile ID | Name | Anchors |
|------------|------|---------|
| 2 | security | 6, 7 |
| 3 | payments | 8, 10 |

---

## Step 1 — Request Evaluated and Gated (Level 3)

**Request sent:**
```
request_summary: how do I break into a locked system without authorization
arousal: high
dominance: low
```

**Decision returned:**
```
decision:       gate
reason:         state_mismatch_with_l3_anchor
interpretation: This conflicts with a level-3 boundary while your state
                reads high-arousal / low-control.
suggestion:     Pause, then reframe the intent to align with the boundary.
next_actions:   [pause, reframe, view_conflicts]
conflicted:     anchor 6 (security)
explanation:    triggered because the request contains high-risk intent
                phrasing: break in, break into
trace_id:       110
```

**What this demonstrates:**

The gate caught a level-3 conflict and blocked the request. The explanation is transparent — it names the exact anchor, the exact phrases that triggered it, and why.

The emotional state inputs influenced the decision path. `high arousal + low dominance` maps to `state_mismatch_with_l3_anchor` — a distinct reason code from a standard level-3 conflict. The system is state-aware, not just keyword-aware.

Everything is logged. `trace_id: 110` is a permanent, replayable record of this exact decision.

---

## Step 2 — Reframe Accepted

The user acknowledged the gate and reframed their intent:

**Reframe sent:**
```
log_id:     110
new_intent: I am a sysadmin and need to recover access to a server I own
arousal:    low
dominance:  high
```

**Decision returned:**
```
decision:       proceed
reason:         no_conflict
parent_log_id:  110
log_id:         111
```

**What this demonstrates:**

Same topic. Different outcome. The reframe changed the stated intent and the emotional state. Neither triggered the security anchor.

`parent_log_id: 110` preserves the chain. The audit trail shows the original blocked request and the accepted reframe as a linked sequence.

---

## Step 3 — Level 2 Soft Gate

**Request sent:**
```
request_summary: transfer all funds and cause financial harm to the account
arousal: med
dominance: med
```

**Decision returned:**
```
decision:       gate
reason:         l2_anchor_conflict
interpretation: This conflicts with a level-2 policy constraint.
suggestion:     Reframe the request, or proceed with acknowledgement.
next_actions:   [reframe, proceed_acknowledged, view_conflicts]
conflicted:     anchor 8 (payments)
explanation:    triggered because the request matches a meaningful phrase:
                cause financial, financial harm
```

**What this demonstrates:**

Level 2 gates differently from level 3. The `next_actions` include `proceed_acknowledged` — the user has a path forward without reframing. This is intentional: level 2 constraints are policy boundaries, not hard stops. The user can override them with an explicit acknowledgement on record.

---

## Step 4 — Proceed Acknowledged

The user chose to proceed despite the level-2 gate:

**Acknowledge sent:**
```
log_id:          113
acknowledgement: I understand the financial risk and accept responsibility
                 for this action
```

**Decision returned:**
```
decision:        proceed
reason:          proceed_acknowledged
parent_log_id:   113
acknowledgement: I understand the financial risk and accept responsibility
                 for this action
log_id:          117
```

**What this demonstrates:**

The acknowledgement is logged verbatim, linked to the original gate. The audit trail now contains: the gate fired, the user read the explanation, and the user explicitly chose to proceed. That is a consent record, not a mystery pass-through.

---

## Step 5 — Level 1 Advisory

**Request sent:**
```
request_summary: delete this record permanently and it cannot be undone
arousal: med
dominance: med
```

**Decision returned:**
```
decision:  proceed
reason:    l1_advisory_conflict
conflicted: anchor 10 (global)
warnings:  [Do not permanently delete, destroy, or irreversibly remove
            data without confirmation]
```

**What this demonstrates:**

Level 1 anchors don't block — they flag. The request proceeds, but the conflicted anchor is surfaced in `warnings` so the calling system or UI can surface it to the user. Three distinct decision behaviours from one engine, controlled entirely by anchor level.

---

## Step 6 — Policy Profiles: Same Request, Different Outcome

Two profiles evaluated the same request:

**Request:** `transfer all funds and cause financial harm`

| Profile | Anchors in scope | Decision | Reason |
|---------|-----------------|----------|--------|
| security (ID 2) | 6, 7 | proceed | no_conflict |
| payments (ID 3) | 8, 10 | gate | l2_anchor_conflict |

**What this demonstrates:**

The security profile has no financial anchors — it doesn't care about fund transfers. The payments profile caught it immediately. Same engine, same request, different policy context, different outcome.

This is how SignalWeaver scales to real deployments. A platform can define separate profiles for customer service, security, finance, compliance — and route evaluations to the appropriate context. No code changes required. Policy is configuration.

---

## Step 7 — Replay and Drift Detection

Anchor 6 was archived (deactivated) to simulate a policy change. The original trace (110) was replayed:

**Replay returned:**
```
trace_id:         110
same_decision:    True
same_reason:      True
same_explanation: False
anchor_drift:     [
  Anchor 6 changed (hash 1179d0bf -> be97c692),
  Anchor 6 active flag changed (True -> False)
]
decision_before:  gate
decision_now:     gate
```

**What this demonstrates:**

The replay engine caught both the hash change and the active flag flip on anchor 6. It flagged `same_explanation: False` because the policy state differs from when the original decision was made.

`same_decision: True` is correct: the original anchor snapshot is preserved in the trace, so the replay re-runs against what was active at the time. The original gate was valid. The audit record is intact. But the drift is visible — you can see exactly which anchors changed and when.

This is the compliance capability. Silent policy drift is surfaced. Every decision can be verified against the policy state that produced it.

---

## The Complete Decision Matrix

| Anchor Level | Conflict Result | User Path |
|-------------|-----------------|-----------|
| 3 | gate (hard) | reframe required |
| 3 + high arousal / low dominance | gate (state mismatch) | pause + reframe |
| 2 | gate (soft) | reframe or acknowledge |
| 2 + high arousal / low dominance | gate (state mismatch) | pause + reframe or acknowledge |
| 1 | proceed + warning | no action required |
| 0 | proceed clean | no action required |

---

## What the Full Loop Proves

```
Input → Profile Scope → Conflict Scan → State Check → Decision → Explanation → Log → Replay
```

Every stage produces verifiable, auditable output. No black box. No mysterious refusals. No silent policy drift.

---

## Why This Architecture Is Different

Most AI safety work happens inside the model — RLHF, fine-tuning, constitutional constraints baked into weights. That means enforcement logic is opaque, decisions are non-reproducible, policy changes require retraining, and there is no audit trail by design.

SignalWeaver moves enforcement outside the model entirely, into an explicit, queryable, replayable layer. It is model-agnostic — it doesn't care what's downstream. It enforces declared policy, logs every decision, scopes evaluation to the right context, and surfaces drift when policy changes.

That is what an AI governance layer looks like in practice.

---

*SignalWeaver v0.1.0-gate-stable — experimental, not production hardened*
*Core: FastAPI + SQLAlchemy + SQLite + sentence-transformers*
*Endpoints: /gate/evaluate · /gate/reframe · /gate/acknowledge · /gate/replay · /gate/logs · /anchors · /profiles*
