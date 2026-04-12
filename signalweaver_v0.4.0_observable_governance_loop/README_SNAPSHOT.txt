================================================================================
SignalWeaver v0.4.0 — Observable Governance Loop
Snapshot Handoff Package
================================================================================

WHAT THIS IS
------------

This archive contains the complete, verified canonical source code for
SignalWeaver at the "Observable Governance Loop" milestone. It represents
the cumulative state after Stages 15 through 22 of incremental development:

  Stage 15: Execution Layer (POST /execute/trusted)
  Stage 16: Execution Analytics (GET /executions, /executions/summary)
  Stage 17: Webhook Connector (real HTTP dispatch)
  Stage 18: Secure Dispatch (8-pattern redaction + HMAC-SHA256 signing)
  Stage 19: Time-Series Analytics (GET /executions/timeseries)
  Stage 20: Alerting Layer (GET /alerts — anomaly detection)
  Stage 21: Outbound Alert Delivery (POST /alerts/dispatch)
  Stage 22: Stabilization, Preservation & Verification Pass

This is a snapshot from a sandbox environment. All files are real, runnable
source code that was verified in-situ.


CANONICAL CODE STRUCTURE
------------------------

  src/app/               Application core
    main.py              FastAPI app entrypoint
    models.py            SQLAlchemy ORM models (9 tables)
    schemas.py           Pydantic request/response schemas
    db.py                SQLite WAL database engine
    gate.py              Deterministic decision logic + enforcement modes
    security.py          API key auth + per-IP rate limiting
    auth.py              Tenant Bearer token auth + key generation
    dependencies.py      Shared FastAPI dependency (get_db)
    embedding_matcher.py Optional semantic matching (sentence-transformers)
    tester.html          Browser-based gate testing UI
    api/                 API endpoint modules
      gate.py            POST /evaluate, POST /reframe, GET /replay, GET /logs
      execute.py         POST /execute/trusted (gate-then-dispatch)
      analytics.py       GET /executions, /summary, /timeseries,
                         GET /governance/insights, GET /compliance/export,
                         GET /alerts, POST /alerts/dispatch
      anchors.py         CRUD for TruthAnchor resources
      tenants.py         Tenant management + API key creation
      profiles.py        PolicyProfile CRUD + anchor assignment
      reports.py         GET /reports/shadow-summary
    connectors/          Execution connector framework
      base.py            Abstract Connector interface
      mock.py            Echo connector (default, for testing)
      webhook.py         Real HTTP webhook dispatch + validation
      redaction.py       8-pattern recursive sensitive field redaction
      signing.py         HMAC-SHA256 request signing
      registry.py        Connector factory (get_connector)
    routers/             Additional routers
      ethos.py           GET /ethos (plain-text ethos invariants)
  src/tests/             Canonical test suite
    conftest.py          Shared fixtures (TestClient, in-memory SQLite)
    test_gate_smoke.py   Gate endpoint smoke tests
    test_gate_flow.py    Decision flow integration tests
    test_refuse.py       Refusal path tests
    test_remediation.py  Remediation path tests
    test_execution.py    Execution layer tests
    test_api_smoke.py    General API smoke tests
    test_analytics.py    Analytics endpoint tests
    test_webhook.py      Webhook connector tests
    test_secure_dispatch.py Redaction + signing tests
    test_alerting.py     Alerting logic tests
    test_alert_dispatch.py  Alert dispatch E2E tests


ROOT-LEVEL FILES
----------------

  requirements.txt       Python dependencies (FastAPI, SQLAlchemy, etc.)
  Dockerfile             Container image definition
  docker-compose.yml     Single-service compose config
  seed.py                Demo data bootstrapper (anchors + profiles)
  README.md              Project README with usage examples
  ETHOS.md               Governance invariants document


DOCS/
----

  STAGE22_STABILIZATION_REPORT.pdf
                        Full Stage 22 stabilization and verification report


WHAT IS INTENTIONALLY EXCLUDED
------------------------------

  backend/               Pre-refactoring stale duplicate (superseded by src/)
  review/                Pre-refactoring flat code tree (superseded by src/)
  tests/                 Older test location (only 2 files; canonical is src/tests/)
  mcp_demo/              MCP demo scripts (not part of core system)
  run.ps1 / test.ps1     Windows PowerShell scripts (convenience only)
  migrate.py             One-time SQLite migration (hardcoded local path)
  *.db                   SQLite database files (runtime data, not source)
  agent_*.py             Ad-hoc agent test scripts
  worklog.md             Internal session worklog
  LICENSING.md / OEM_PITCH.md / DEMO.md / TEST_EVIDENCE.md
                         Supplementary docs (not required to run the system)
  security_patches.diff  Historical patch file
  generate_*.py          Report generator scripts (used to create PDFs)
  insight_report.json    Generated insight data
  __pycache__ / *.pyc    Python bytecode caches


KNOWN NOTES
-----------

1. Missing __init__.py files: src/, src/app/, src/tests/, and src/app/routers/
   do not have __init__.py files. The system works because PYTHONPATH is set
   to src/ (in Dockerfile) or sys.path is modified in conftest.py. Python 3.3+
   namespace package support makes this work, but adding explicit __init__.py
   files is recommended for production.

2. The Dockerfile expects files at COPY src /app/src — the src/ directory in
   this archive is the one to copy.

3. The seed.py script requires a running server at localhost:8000.

4. Tests should be run from the src/ directory:
      cd src && python -m pytest tests/ -v

5. Multi-tenant isolation: all query paths in gate.py, execute.py, and
   analytics.py properly scope by tenant_id. The tenant system uses Bearer
   token auth (api_key_hash in tenants table).


TECHNOLOGY STACK
----------------

  Python 3.10+
  FastAPI 0.115.0
  SQLAlchemy 2.0.32 (ORM)
  SQLite with WAL mode
  Pydantic 2.8.2
  requests 2.32.3 (webhook HTTP)
  httpx 0.27.2
  pytest + TestClient (testing)
  uvicorn (ASGI server)


GENERATED
---------

  Snapshot created: 2026-04-06
  Source: AI sandbox environment (session-based, non-persistent)
  Archive format: .zip
