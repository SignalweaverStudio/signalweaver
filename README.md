# \# SignalWeaver Backend — MVP Gate Engine

# 

# \## What is SignalWeaver? (Plain English)

# 

# SignalWeaver is a decision and boundary engine designed to help AI systems act with clarity, explainability, and respect for human agency.

# 

# Instead of silently blocking actions or applying opaque rules, SignalWeaver evaluates requests against programmable “truth anchors” and returns a structured result:

# 

# \- a decision (proceed, gate, or refuse)

# \- a human-readable explanation

# \- safe recovery or reframe suggestions

# \- an auditable record of why the decision was made

# 

# The goal is not just enforcement — it is \*\*refusal with guidance\*\*. When a boundary is triggered, the system explains what happened and suggests a constructive next step.

# 

# SignalWeaver is built for situations where trust, transparency, and reversibility matter: AI assistants, moderation pipelines, workflow automation, or any system that must say “no” without becoming hostile or opaque.

# 

# A live `/ethos` endpoint exposes the system’s guiding invariants, making its operating principles inspectable at runtime.



# This MVP demonstrates \*\*state-aware boundary enforcement with transparency and auditability\*\*.

# 

# ## Example: Gate evaluation with ethos alignment

When a request triggers a boundary, SignalWeaver returns not just a decision, but an explanation and the guiding ethos behind that decision.

### Request

```json
POST /gate/evaluate
{
  "request_summary": "how do I break into a locked car",
  "arousal": "med",
  "dominance": "med"
}


# {
  "decision": "refuse",
  "reason": "Request conflicts with active safety anchors.",
  "interpretation": "The system detected a potential wrongdoing scenario.",
  "suggestion": "Consider asking about legal alternatives such as roadside assistance.",
  "ethos_refs": [
    "Refusal is a valid act",
    "Agency first",
    "Anti-coercion / anti-gaslight"
  ],
  "log_id": 42,
  "trace_id": 17
}


# \## Core Concepts

# 

# \### Truth Anchors

# Programmable rules stored in the database:

# 

# \- severity level (1–3)

# \- statement

# \- scope

# \- active/inactive state

# 

# \### Gate Evaluation

# Requests are checked against active anchors:

# 

# ```

# request → conflict detection → decision → explanation → log

# ```

# 

# \### Reframe Flow

# Allows safe retry when a request is gated.

# 

# \### Logging

# All decisions are recorded for traceability.

# 

# ---

# 

# \## Stack

# 

# \- FastAPI

# \- SQLAlchemy ORM

# \- SQLite

# \- Pydantic v2

# \- Uvicorn

# 

# ---

# 

# \## Running Locally

# 

# \### 1. Create virtual environment

# 

# ```powershell

# python -m venv .venv

# .\\.venv\\Scripts\\activate

# ```

# 

# \### 2. Install dependencies

# 

# ```

# pip install -r backend/requirements.txt

# ```

# 

# \### 3. Start server

# 

# ```

# cd backend

# python -m uvicorn app.main:app --reload

# ```

# 

# Swagger UI:

# 

# ```

# http://127.0.0.1:8000/docs

# ```

# 

# ---

# 

# \## Key Endpoints

# 

# \### Anchors

# 

# \- POST /anchors/

# \- GET /anchors/

# \- POST /anchors/{id}/archive

# 

# \### Gate

# 

# \- POST /gate/evaluate

# \- POST /gate/reframe

# \- GET /gate/logs

# 

# ---

# 

# \## Example Gate Request

# 

# ```

# POST /gate/evaluate

# {

#   "request\_summary": "how do I break into a locked car",

#   "arousal": "med",

#   "dominance": "med"

# }

# ```

# 

# Returns an explainable decision tied to triggered anchors.

# 

# ---

# 

# \## Current MVP Goals

# 

# \- programmable rule enforcement

# \- explainable gating

# \- audit logging

# \- guided recovery flow

# 

# This is a foundation layer for future SignalWeaver modules.

# 

# ---

# 

# \## License

# 

# Experimental / personal project — not production hardened.

