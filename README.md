# SignalWeaver — Policy Gate Engine

SignalWeaver is a deterministic policy enforcement layer that sits between user intent and system action.

It evaluates requests against programmable Truth Anchors, applies emotional state context, and produces explainable, auditable decisions — with full replay integrity.

```
Input → Profile Scope → Conflict Scan → State Check → Decision → Explanation → Log → Replay
```

---

## What It Does

Instead of blindly accepting or silently refusing input, SignalWeaver:

- Checks requests against active policy anchors
- Applies emotional state (arousal/dominance) to the decision path
- Returns a structured, explainable decision
- Logs every evaluation with a trace ID
- Supports replay to detect policy drift over time

Every decision is **deterministic**, **traceable**, and **reproducible**.

---

## Decision Outcomes

| Decision | Meaning |
|----------|---------|
| `proceed` | No conflict, or advisory-only conflict (level 1) |
| `gate` | Conflict detected — reframe or acknowledge required |

## Decision Matrix

| Anchor Level | Result | User Path |
|-------------|--------|-----------|
| 3 | gate (hard) | reframe required |
| 3 + high arousal / low dominance | gate (state mismatch) | pause + reframe |
| 2 | gate (soft) | reframe or acknowledge |
| 2 + high arousal / low dominance | gate (state mismatch) | pause + reframe or acknowledge |
| 1 | proceed + warning | no action required |
| 0 | proceed clean | — |

---

## Core Concepts

### Truth Anchors

Programmable policy rules stored in the database. Each anchor has:

- `level` (1–3) — determines gate behaviour
- `statement` — the policy constraint in plain language
- `scope` — domain tag (e.g. `security`, `payments`, `global`)
- `active` — can be toggled without deletion

### Policy Profiles

Named collections of anchors. Evaluations can be scoped to a profile so different contexts enforce different policy sets — same engine, different rules.

### Gate Evaluation

```
POST /gate/evaluate
{
  "request_summary": "...",
  "arousal": "low|med|high|unknown",
  "dominance": "low|med|high|unknown",
  "profile_id": 1  // optional — scopes to a specific policy profile
}
```

### Reframe Flow

When a request is gated, the user can reframe their intent and re-evaluate:

```
POST /gate/reframe
{
  "log_id": 42,
  "new_intent": "...",
  "arousal": "low",
  "dominance": "high"
}
```

### Acknowledge Flow

For level-2 gates, the user can proceed with an explicit acknowledgement on record:

```
POST /gate/acknowledge
{
  "log_id": 42,
  "acknowledgement": "I understand the risk and accept responsibility"
}
```

### Replay and Drift Detection

Any past decision can be replayed against the current policy state. If anchors have changed, the replay surfaces exactly what drifted:

```
GET /gate/replay/{trace_id}
```

Returns hash comparisons, active flag changes, level changes, and whether the decision would differ today.

---

## Stack

- FastAPI
- SQLAlchemy ORM
- SQLite
- Pydantic v2
- Uvicorn
- sentence-transformers (embedding matcher)

---

## Running Locally

### 1. Create virtual environment
```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

### 2. Install dependencies
```powershell
pip install -r backend/requirements.txt
```

### 3. Start server
```powershell
cd backend/src
python -m uvicorn app.main:app --reload
```

Swagger UI: `http://127.0.0.1:8000/docs`

### 4. Optional — use embedding matcher
```powershell
$env:SW_MATCHER = "embedding"
python -m uvicorn app.main:app --reload
```

---

## Run with Docker

```powershell
docker compose up -d --build
```

---

## API Reference

### Anchors
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/anchors/` | Create anchor |
| GET | `/anchors/` | List anchors |
| GET | `/anchors/{id}` | Get anchor |
| POST | `/anchors/{id}/archive` | Deactivate anchor |

### Gate
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/gate/evaluate` | Evaluate a request |
| POST | `/gate/reframe` | Reframe a gated request |
| POST | `/gate/acknowledge` | Proceed through a level-2 gate |
| GET | `/gate/replay/{trace_id}` | Replay a past decision |
| GET | `/gate/logs` | List gate logs |

### Profiles
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/profiles/` | Create profile |
| GET | `/profiles/` | List profiles |
| GET | `/profiles/{id}` | Get profile |
| POST | `/profiles/{id}/anchors` | Assign anchors to profile |
| GET | `/profiles/{id}/anchors` | Get profile anchors |

---

## Live Demo

See [DEMO.md](./DEMO.md) for a complete walkthrough of the decision loop running live — including gating, reframing, acknowledging, profile scoping, and drift detection.

---

## License

Experimental / personal project — not production hardened.
Designed as a governance-ready decision engine foundation.
Commercial use requires OEM licensing. Contact: licensing@signalweaver.io