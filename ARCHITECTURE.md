\# SignalWeaver Architecture



\## Overview



SignalWeaver is a deterministic governance layer that sits between AI systems and real-world actions.



It evaluates proposed actions against defined policy rules ("anchors") and returns a decision:



\- proceed

\- gate (hold for review)

\- refuse



Every decision is logged and can be replayed to verify consistency.



\---



\## Core Flow



1\. A request is sent to `/gate/evaluate`

2\. Active policy anchors are loaded

3\. The request is checked for conflicts

4\. A decision is returned with reasoning

5\. The full decision is logged with a trace



\---



\## Key Concepts



\### Anchors

Policy rules that define what is allowed.



Examples:

\- "Do not approve refunds above £10,000 without review"



Levels:

\- L1: advisory

\- L2: soft constraint (gate)

\- L3: hard constraint (gate/refuse)



\---



\### Decision Engine



Located in:



src/app/gate.py



Responsibilities:

\- evaluate requests

\- detect conflicts

\- determine outcome

\- generate explanations

\- create trace records



\---



\### Replay System



Endpoint:



GET /gate/replay/{trace\_id}



Allows:

\- re-running past decisions

\- detecting policy drift

\- verifying determinism



\---



\### API Layer



Routes located in:



src/app/api/



Key endpoints:

\- POST /gate/evaluate

\- GET /gate/replay/{trace\_id}

\- POST /anchors/

\- GET /anchors/

\- POST /profiles/

\- GET /reports/



\---



\### Data Models



Defined in:



src/app/models.py



Key entities:

\- Anchor

\- GateLog

\- DecisionTrace

\- Tenant

\- Profile



\---



\## Multi-Tenant Design



\- Each tenant has an API key

\- Data is scoped per tenant

\- No cross-tenant leakage



\---



\## Current State



Stable:

\- Core decision engine

\- Replay system

\- Policy anchors

\- Multi-tenant support



In progress:

\- Stage 14: external connectors (three-phase execution model)



\---



\## Design Principle



SignalWeaver is designed to be:



\- deterministic

\- explainable

\- auditable



See ETHOS.md for full design invariants.

