SignalWeaver Backend — Deterministic Policy Gate Engine

SignalWeaver is a deterministic backend engine that evaluates user requests against programmable Truth Anchors (rules) and produces explainable, replayable decisions.

Unlike simple rule checks, SignalWeaver:

Stores full decision traces

Snapshots evaluated anchors

Supports replay with consistency guarantees

Detects anchor drift over time

Returns structured, human-readable explanations

This MVP demonstrates state-aware boundary enforcement with transparency, auditability, and reproducibility.

Core Capabilities
Truth Anchors

Programmable rule objects stored in the database:

severity level (1–3)

statement

scope

active/inactive state

stable hash for trace consistency

Deterministic Gate Evaluation
request → conflict detection → decision → explanation → trace snapshot

Decisions are:

proceed

gate

refuse

Each evaluation stores:

decision + reason

explanation

anchor snapshot (including match state)

trace ID for replay

Replay Engine

GET /gate/replay/{trace_id}

Replay guarantees:

Same decision logic

Same explanation (stored snapshot)

Detection of newly added anchors since original trace

Deterministic re-evaluation path

This allows auditability and policy evolution tracking.

Reframe Flow

When gated, the system provides:

explanations

recovery suggestions

structured next actions

Stack

FastAPI

SQLAlchemy 2.x

SQLite

Pydantic v2

Uvicorn

Pytest (minimal smoke tests)

Running Locally
1. Create virtual environment
python -m venv .venv
.\.venv\Scripts\activate
2. Install dependencies
pip install -r requirements.txt
3. Start server
uvicorn app.main:app --reload

Swagger UI:

http://127.0.0.1:8000/docs
Key Endpoints
Anchors

POST /anchors/

GET /anchors/

POST /anchors/{id}/archive

Gate

POST /gate/evaluate

POST /gate/reframe

GET /gate/replay/{trace_id}

GET /gate/logs

MVP Goals Achieved

Deterministic rule enforcement

Replayable audit traces

Explainable decisions

Anchor drift transparency

Minimal rate limiting

Smoke-tested core behaviour

Status

Experimental / not production hardened.

Designed as a governance-ready decision engine foundation.