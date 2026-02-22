\# SignalWeaver — OEM / On-Prem Integration Overview



\## What It Is



SignalWeaver is a deterministic policy gate engine designed to sit between user input and system action.



It evaluates requests against programmable policy anchors and produces:



\- Deterministic decisions

\- Trace IDs for every evaluation

\- Replayable decision paths

\- Drift detection when policy changes

\- Structured, explainable output



SignalWeaver is not a model.

It is a boundary enforcement and audit layer.



---



\## Problem It Solves



Modern AI systems face three structural risks:



1\. Non-deterministic decision behaviour

2\. Lack of reproducible audit trails

3\. Policy drift over time without visibility



SignalWeaver addresses these by enforcing:



\- Deterministic evaluation logic

\- Replayable trace architecture

\- Explicit anchor-based policy design

\- Transparent conflict explanation



---



\## Where It Fits



SignalWeaver can be embedded:



\- As a pre-execution gate in SaaS platforms

\- As an internal AI governance layer

\- As a compliance audit boundary

\- As a deterministic evaluation service in regulated environments



Deployment models:



\- On-prem Docker service

\- OEM embedded component

\- Future SDK integration

## Typical Integration Pattern

User Request → SignalWeaver `/gate/evaluate` → Decision + Trace ID →  
If `proceed` → Downstream system executes  
If `gate/refuse` → Controlled response returned  

SignalWeaver does not replace business logic.  
It enforces deterministic policy boundaries before execution.



---



\## Why Determinism Matters



In regulated or enterprise environments, the ability to:



\- Reproduce decisions

\- Verify policy state at time of evaluation

\- Detect post-decision policy drift



is more important than raw AI capability.



SignalWeaver provides that structural layer.



---



\## Current State (v0.1.0-gate-stable)



\- Deterministic gate engine operational

\- Replay integrity verified

\- Docker deployment validated

\- Licensing model defined for OEM use



Not production hardened yet. Designed as a governance-ready foundation.



---



\## Commercial Model



Commercial use requires OEM licensing.



Intended models:



\- Annual enterprise license

\- Per-deployment on-prem license

\- Custom integration agreements



For OEM discussion:

licensing@signalweaver.io

