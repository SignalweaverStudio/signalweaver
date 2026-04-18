\# SignalWeaver — Phase 2 Shadow Checkpoint

Date: 2026-04-18



\## System State

\- Phase 2 (confidence-aware resolution) implemented

\- Shadow mode active

\- Analysis pipeline operational:

&#x20; - export-shadow-traces

&#x20; - analyze

&#x20; - review-pack



\## Data Sources

\- backend/signalweaver.db → ACTIVE

\- signalweaver.db (root) → no shadow data

\- data/signalweaver.db → no shadow data



\## Results (backend DB)

\- Total shadow records: 11

\- Override rate: 0.00%

\- Agreement rate: 100.00%

\- Total overrides: 0

\- Avg overrides/event: 0.00

\- Invariant violations: 0

\- Confidence histogram: empty (no overrides)



\## Interpretation

\- Phase 2 shadow pipeline functioning correctly

\- No invariant violations observed

\- No overrides triggered yet

\- Sample size insufficient for evaluation



\## Status

Continue shadow mode (per Phase 2 plan thresholds)



\## Notes

\- Exporter patched for backward compatibility (tenant\_id optional)

\- Analysis + review tooling validated

\- Only backend DB contains usable shadow data



\## Next Steps

\- Increase sample size (target: 500+ records)

\- Generate targeted probe inputs to exercise same-anchor collision

\- Monitor override emergence over time

