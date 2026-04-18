"""
Enable ``python -m app.analysis`` to run the Phase 2 shadow utilities.

Usage
-----
    python -m app.analysis export-shadow-traces --output traces.json
    python -m app.analysis analyze --input traces.json
    python -m app.analysis review-pack --input traces.json --count 20
"""

from app.analysis.export_shadow_traces import cli_main
import sys

sys.exit(cli_main())