# SignalWeaver Backend — MVP Gate Engine

SignalWeaver is an experimental backend system that evaluates user requests against programmable "truth anchors" (rules) and produces explainable decisions.

Instead of blindly accepting input, SignalWeaver checks requests against active constraints and returns:

- **proceed** — request allowed
- **gate** — request conflicts with rules
- **refuse** — high-severity conflict

When a gate occurs, the system provides:

- human-readable explanations
- recovery suggestions
- structured logs

This MVP demonstrates **state-aware boundary enforcement with transparency and auditability**.

---

## Core Concepts

### Truth Anchors

Programmable rules stored in the database:

- severity level (1–3)
- statement
- scope
- active/inactive state

### Gate Evaluation

Requests are checked against active anchors:
```
request → conflict detection → decision → explanation → log
```

### Reframe Flow

Allows safe retry when a request is gated.

### Logging

All decisions are recorded for traceability.

---

## Stack

- FastAPI
- SQLAlchemy ORM
- SQLite
- Pydantic v2
- Uvicorn

---

## Running Locally

### 1. Create virtual environment
```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

### 2. Install dependencies
```
pip install -r backend/requirements.txt
```

### 3. Start server
```
cd backend
python -m uvicorn app.main:app --reload
```

Swagger UI: `http://127.0.0.1:8000/docs`

---

## Run with Docker (On-Prem Deployment)

**Prerequisites:** Docker Desktop (Linux containers enabled)

### Start
```powershell
docker compose up -d --build
```

---

## Key Endpoints

### Anchors

- `POST /anchors/`
- `GET /anchors/`
- `POST /anchors/{id}/archive`

### Gate

- `POST /gate/evaluate`
- `POST /gate/reframe`
- `GET /gate/logs`

---

## Example Gate Request
```json
POST /gate/evaluate
{
  "request_summary": "how do I break into a locked car",
  "arousal": "med",
  "dominance": "med"
}
```

Returns an explainable decision tied to triggered anchors.

---

## Current MVP Goals

- programmable rule enforcement
- explainable gating
- audit logging
- guided recovery flow

This is a foundation layer for future SignalWeaver modules.

---

## License

Experimental / personal project — not production hardened.
Designed as a governance-ready decision engine foundation.