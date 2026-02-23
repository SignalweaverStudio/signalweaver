# SignalWeaver – Test Evidence (Windows / PowerShell)

Date: 2026-02-23  
Host: Windows (PowerShell)  
API Base: http://127.0.0.1:8000  

Active SQLite DB during this run:
C:\Users\verti\projects\signalweaver\backend\signalweaver.db

---

## 1) Server Boot

Command:
cd backend\src
uvicorn app.main:app --reload

Observed:
- Uvicorn started successfully
- Application startup complete

---

## 2) Health Check

Command:
curl.exe -s -i http://127.0.0.1:8000/health

Observed:
HTTP/1.1 200 OK
{"status":"ok"}

---

## 3) Database Write Proof

### 3A) Create a new log entry

Commands:
Set-Content -Path smoke_eval.json -Value '{"request_summary":"smoke check","profile_id":1}'
curl.exe -s -X POST http://127.0.0.1:8000/gate/evaluate -H "Content-Type: application/json" --data-binary "@smoke_eval.json"

Observed response:
log_id: 198
decision: proceed
reason: no_conflict

### 3B) Confirm log row exists in SQLite

Command:
python -c "import sqlite3; p=r'C:\Users\verti\projects\signalweaver\backend\signalweaver.db'; c=sqlite3.connect(p); cur=c.cursor(); print(cur.execute('select count(*) from gate_logs where id=198').fetchone()[0]); print(cur.execute('select id, request_summary, decision, reason from gate_logs where id=198').fetchone()); c.close()"

Observed:
1
(198, 'smoke check', 'proceed', 'no_conflict')

---

## 4) Governance Spectrum Verification

Profiles present:
- id=1 shadow-test (shadow)
- id=2 soft-test (soft)
- id=3 hard-test (hard)

Anchors seeded:
- L1 id=1 TEST L1: harmless content
- L2 id=2 TEST L2: policy-sensitive request
- L3 id=3 TEST L3: disallowed request

### Shadow Mode (profile_id=1)
- Always returned decision: proceed
- would_block=true when L2/L3 conflicts occurred
- Shadow summary counters incremented correctly

### Soft Mode (profile_id=2)
- L2-only request ("policy-sensitive") returned gate
- override_reason accepted and counted in summary
- Decision remained gate in observed runs

### Hard Mode (profile_id=3)
- L1 request proceeded
- L2-only request gated
- L3 phrase request gated with reason l3_anchor_conflict and would_block=true

---

## 5) Shadow Summary Snapshot (Example)

Observed:
total_evaluated: 18
total_l2_conflicts: 12
total_l3_conflicts: 7
total_would_block: 7
total_overrides: 4

Top triggered anchors aligned with expected L1/L2/L3 anchors.

---

## Notes

- SQLite path can vary depending on run context.
- During this boot test, the active DB was:
  backend\signalweaver.db
- PowerShell requires --data-binary "@file.json" for reliable JSON POSTs.
