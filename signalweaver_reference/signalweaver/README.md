# SignalWeaver — Deterministic Governance Substrate (Reference Prototype)

> *"Govern consequence, never intelligence."*

A minimal, hermetic proof-of-protocol for deterministic AI governance.
No databases. No APIs. No LLMs. No probabilistic scoring.
Pure Python 3.11 + standard library + pytest.

---

## What This Is

A reference implementation of the SignalWeaver governance substrate — the decision
layer that sits between machine intent and machine action.

It proves seven properties:

| # | Property | Module |
|---|----------|--------|
| 1 | MachineTraceFrame normalisation | `core/frame.py` |
| 2 | SW-CER canonical serialisation | `core/canonicalizer.py` |
| 3 | Deterministic policy evaluation | `core/evaluator.py` |
| 4 | Monotonic escalation resolution | `core/evaluator.py` |
| 5 | Trace emission | `core/replay.py` |
| 6 | Replay from cold boot | `core/replay.py` |
| 7 | Bitwise replay invariance | `tests/test_replay.py` |

---

## Directory Structure

```
signalweaver/
├── core/
│   ├── __init__.py
│   ├── frame.py          # MachineTraceFrame — frozen, immutable, no floats
│   ├── canonicalizer.py  # SW-CER: deterministic canonical JSON bytes
│   ├── hashes.py         # SHA-256 over canonical bytes
│   ├── policy.py         # Static policy pack (POL-000 through POL-300)
│   ├── evaluator.py      # Deterministic evaluation + monotonic escalation
│   └── replay.py         # Trace emission + cold-boot replay
├── examples/
│   ├── __init__.py
│   └── treasury_airlock.py   # Reference scenario
├── tests/
│   ├── __init__.py
│   ├── test_canonicalization.py
│   ├── test_monotonicity.py
│   └── test_replay.py
└── README.md
```

---

## Protocol Summary

### MachineTraceFrame

The atomic unit of observable behaviour. Frozen dataclass. No floats anywhere.
Tags normalised to sorted, deduplicated tuples at construction time.
JSON serialisation is byte-stable.

```python
frame = MachineTraceFrame.build(
    frame_id="treasury-001",
    timestamp_ms=1_700_000_001_000,
    actor="actor:treasury:automated",
    action="transfer.outbound",
    payload={"amount_pence": 2_500_000},
    tags=["treasury", "outbound"],
)
```

### SW-CER (Canonical Encoding Rules)

- Lexicographic key ordering (recursive)
- UTF-8, no BOM, no whitespace variance
- Homogeneous lists sorted deterministically
- Output is a `bytes` object — identical for identical logical content

```python
canonical_bytes = canonicalise(frame.to_dict())
frame_hash = hash_canonical(canonical_bytes)
```

### Verdict States

| Constant | Value | Meaning |
|----------|-------|---------|
| `PROCEED` | 0 | No constraint matched — allow |
| `EXPLORE` | 1 | Ambiguous state — log and proceed with caution |
| `GATE`    | 2 | Human approval required |
| `REFUSE`  | 3 | Hard block — do not execute |

Resolution: `max()` over all policy signals. Highest always dominates.
A REFUSE can never be reduced to GATE by a subsequent policy.

### Static Policy Pack

| Policy | Trigger | Verdict |
|--------|---------|---------|
| POL-000 | Always | PROCEED |
| POL-100 | `transfer.outbound` amount > £10k | GATE |
| POL-100 | `transfer.outbound` amount > £100k | REFUSE |
| POL-101 | `transfer.outbound` velocity ≥ 5/h | GATE |
| POL-200 | Actor on static blocklist | REFUSE |
| POL-300 | Tags: `sensitive` + `unreviewed` | GATE |

---

## Running the Example

```powershell
# From the repo root
python examples/treasury_airlock.py
```

Expected output (truncated):
```
============================================================
SIGNALWEAVER — Treasury Airlock Scenario
============================================================

  Frame   : treasury-001
  Verdict : PROCEED  (0)
  ...

  Frame   : treasury-002
  Verdict : GATE  (2)
  ...

  Frame   : treasury-003
  Verdict : REFUSE  (3)
  ...

Replay INVARIANT: VERIFIED — bitwise identical.
ALL CHECKS PASSED.
```

---

## Running the Tests

```powershell
# From the repo root
pytest tests/ -v
```

All tests are hermetic. No network. No disk state shared between tests
(each test that needs a trace log creates a fresh temp file).

---

## Design Constraints (Enforced)

- **No floats.** `timestamp_ms` and all payload values must be integers.
- **No external dependencies.** Standard library + pytest only.
- **No probabilistic scoring.** Policies are pure boolean/integer predicates.
- **No dynamic loading.** Policy registry is a static Python list.
- **No LLM calls.** No embeddings. No semantic interpretation.
- **Deterministic.** Same input → same output, always, on any machine.
- **Replayable.** The trace log is the only persistent state. Cold-boot replay
  must reproduce identical verdicts and identical hashes.

---

## Extending the Policy Pack

Add a new function to `core/policy.py` following the `PolicyFn` signature:

```python
def policy_my_new_rule(frame) -> PolicySignal:
    if <condition>:
        return PolicySignal(verdict=GATE, reason="...", policy_id="POL-400")
    return PolicySignal(verdict=PROCEED, reason="Not in scope.", policy_id="POL-400")
```

Then append it to `POLICY_REGISTRY`. No other changes required.

---

*Python 3.11 · stdlib only · pytest · no external runtime dependencies*
