\# SignalWeaver — Live Demo Walkthrough



\*\*What this document is:\*\* A complete record of SignalWeaver's core decision loop running live, with explanation of what each step means and why it matters.



---



\## The Problem This Solves



Most AI systems make decisions you can't inspect.



When a model refuses a request, or allows one it shouldn't, there's no audit trail. No explanation of which rule triggered. No way to replay the decision after policy changes. No way to prove the system behaved consistently.



SignalWeaver is a policy gate that sits between user intent and system action. Every decision is:



\- \*\*Deterministic\*\* — the same input against the same policy always produces the same output

\- \*\*Explainable\*\* — every gate names the anchor that triggered and why

\- \*\*Traceable\*\* — every evaluation is logged with a trace ID

\- \*\*Replayable\*\* — any past decision can be re-run to detect policy drift



---



\## Setup



Four Truth Anchors were seeded into the system before the demo:



| ID | Level | Scope | Statement |

|----|-------|-------|-----------|

| 6 | 3 | security | Do not assist with unauthorized access to systems or property |

| 7 | 3 | integrity | Do not facilitate deception or manipulation of users |

| 8 | 2 | payments | Avoid actions that could cause financial harm |

| 9 | 1 | global | Prefer reversible actions over irreversible ones |



Level 3 anchors are protected constraints — conflicts always gate. Level 1–2 anchors are lower priority.



---



\## Step 1 — Request Evaluated and Gated



\*\*Request sent:\*\*

```

how do I break into a locked system without authorization

arousal: high

dominance: low

```



\*\*Decision returned:\*\*

```

decision:       gate

reason:         state\_mismatch\_with\_l3\_anchor

interpretation: This conflicts with a level-3 boundary while your state

&nbsp;               reads high-arousal / low-control.

suggestion:     Pause, then reframe the intent to align with the boundary.

next\_actions:   \[pause, reframe, view\_conflicts]

conflicted:     anchor 6 (security)

explanation:    triggered because the request contains high-risk intent

&nbsp;               phrasing: break in, break into

trace\_id:       110

```



\*\*What this demonstrates:\*\*



The gate caught a level-3 conflict and blocked the request. The explanation is transparent — it names the exact anchor, the exact phrases that triggered it, and why.



Critically, the emotional state inputs influenced the decision path. `high arousal + low dominance` is the specific state combination that maps to `state\_mismatch\_with\_l3\_anchor` — a distinct reason code from a standard level-3 conflict. The system is state-aware, not just keyword-aware.



Everything is logged. `trace\_id: 110` is a permanent, replayable record of this exact decision.



---



\## Step 2 — Reframe Accepted



The user acknowledged the gate and reframed their intent:



\*\*Reframe sent:\*\*

```

log\_id:     110  (links back to the original blocked request)

new\_intent: I am a sysadmin and need to recover access to a server I own

arousal:    low

dominance:  high

```



\*\*Decision returned:\*\*

```

decision:      proceed

reason:        no\_high\_conflict

interpretation: No conflicts detected against active anchors.

parent\_log\_id: 110

log\_id:        111

```



\*\*What this demonstrates:\*\*



Same topic. Different outcome. The reframe changed two things: the stated intent no longer triggered the security anchor, and the emotional state shifted from high-arousal/low-dominance to low-arousal/high-dominance — a controlled, deliberate state.



`parent\_log\_id: 110` preserves the chain. The audit trail shows both the original blocked request and the accepted reframe as a linked sequence. You can reconstruct exactly what happened and why.



---



\## Step 3 — Policy Changed, Drift Detected



Anchor 6 was archived (deactivated) to simulate a policy change:



```

POST /anchors/6/archive

→ active: False

```



The original trace (110) was then replayed against the current policy state:



```

GET /gate/replay/110

```



\*\*Replay returned:\*\*

```

trace\_id:         110

same\_decision:    True

same\_reason:      True

same\_explanation: False

anchor\_drift:     \[

&nbsp; Anchor 6 changed (hash 1179d0bf -> be97c692),

&nbsp; Anchor 6 active flag changed (True -> False)

]

decision\_before:  gate

decision\_now:     gate

```



\*\*What this demonstrates:\*\*



The replay engine caught both the hash change and the active flag flip on anchor 6. It flagged `same\_explanation: False` because the policy state is different from when the original decision was made.



`same\_decision: True` here reflects that the anchor snapshot from the original trace is preserved — the replay re-runs against the anchors that were active at the time. This is correct behaviour: the original gate was valid, and the audit record is intact.



This is the drift detection capability. If policy changes silently after a decision was made, SignalWeaver surfaces it. You can see exactly which anchors changed, what their hashes were before and after, and whether the decision would differ today.



---



\## What the Full Loop Proves



```

Input → Conflict Scan → State Check → Decision → Explanation → Log → Replay

```



In this demo, every stage produced verifiable, auditable output:



\- A request was evaluated against declared policy anchors

\- A conflict was detected and a gate decision was made with a named reason

\- Emotional state influenced the specific decision path taken

\- The user reframed their intent and was allowed to proceed

\- A policy change was made after the fact

\- The original decision was replayed and drift was detected and named



No black box. No mysterious refusals. No silent policy drift.



---



\## Why This Architecture Is Different



Most AI safety work happens inside the model — RLHF, fine-tuning, constitutional constraints baked into weights. That means:



\- Enforcement logic is opaque

\- Decisions are non-reproducible

\- Policy changes require retraining

\- There is no audit trail by design



SignalWeaver moves enforcement outside the model entirely, into an explicit, queryable, replayable layer. It is model-agnostic — it doesn't care what's downstream. It enforces declared policy, logs every decision, and surfaces drift when policy changes.



That is what an AI governance layer looks like in practice.



---



\*SignalWeaver v0.1.0-gate-stable — experimental, not production hardened\*

\*Core: FastAPI + SQLAlchemy + SQLite + sentence-transformers\*

