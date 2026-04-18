"""
export_shadow_traces.py — Pull DecisionTrace rows containing Phase 2 shadow
data from the SignalWeaver database and export them as JSON.

This is the data bridge between the live database and the offline analysis
module (phase2_shadow_analysis.py).  No production behaviour changes.

Usage
-----
    python -m app.analysis export-shadow-traces --output traces.json
    python -m app.analysis export-shadow-traces --limit 50 --since 2025-01-01
    python -m app.analysis review-pack --output review.json --count 20

Design notes
------------
- Reads from the same SQLite DB that the running server uses (or a custom
  path via ``--db``).
- Filters rows where ``match_debug_json`` contains
  ``phase2_shadow.active = true`` using SQLite's ``json_extract``.
- Falls back to Python-side filtering if ``json_extract`` is unavailable
  (older SQLite builds).
- Output format is a JSON array of dicts, each with the DecisionTrace
  scalar fields plus a parsed ``match_debug_json`` dict — exactly the
  shape expected by ``phase2_shadow_analysis.py`` functions.
- The review-pack sub-command reshapes the same data into a compact
  format optimised for manual review (request text, would_change,
  confidence, reasons).
- Backward-compatible with older DB schemas where ``tenant_id`` may not
  exist: the exporter introspects the table schema at runtime and omits
  columns that are not present, filling them with ``None`` in the output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text, func, select
from sqlalchemy.orm import Session, sessionmaker


# ───────────────────────────────────────────────────────────────
# DB helpers
# ───────────────────────────────────────────────────────────────


def _make_engine(db_path: str | Path) -> Any:
    """Create a read-only SQLAlchemy engine for the SQLite database."""
    db_path = Path(db_path).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    url = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
    )
    return engine


def _default_db_path() -> Path:
    """Resolve the default database path (same logic as app.db)."""
    base_dir = Path(__file__).resolve().parents[2]  # .../src/
    return base_dir / "signalweaver.db"


# ───────────────────────────────────────────────────────────────
# Schema introspection
# ───────────────────────────────────────────────────────────────


#: The full set of columns we want to export.
_FULL_COLUMNS: List[str] = [
    "id", "created_at", "policy_profile_id", "request_text",
    "request_normalized", "arousal", "dominance", "decision",
    "reason", "explanation", "match_debug_json", "would_block",
    "enforcement_mode_snapshot", "override_reason", "tenant_id",
]


def _detect_columns(session: Session) -> List[str]:
    """
    Return the subset of ``_FULL_COLUMNS`` that actually exist in the
    ``decision_traces`` table of the current database.

    Uses ``PRAGMA table_info(decision_traces)`` to introspect the schema.
    Falls back to the full column list if introspection fails (so that
    downstream errors are still raised with their original message).
    """
    try:
        rows = session.execute(
            text("PRAGMA table_info(decision_traces)")
        ).fetchall()
        existing = {row[1] for row in rows}  # row[1] is the column name
        return [col for col in _FULL_COLUMNS if col in existing]
    except Exception:
        # If introspection itself fails, assume all columns exist.
        # The downstream query will raise a clear error if wrong.
        return list(_FULL_COLUMNS)


def _pad_record(record: Dict[str, Any], columns: List[str]) -> Dict[str, Any]:
    """
    Ensure *record* contains every key from ``_FULL_COLUMNS``.

    Columns that were not present in the DB get a value of ``None``.
    This guarantees a stable output shape regardless of schema version.
    """
    for col in _FULL_COLUMNS:
        if col not in record:
            record[col] = None
    return record


# ───────────────────────────────────────────────────────────────
# Core export logic
# ───────────────────────────────────────────────────────────────


def export_shadow_traces(
    db_path: Optional[str | Path] = None,
    limit: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Query DecisionTrace rows containing active Phase 2 shadow data.

    Parameters
    ----------
    db_path : str or Path, optional
        Path to the SQLite database file.  Defaults to the same path the
        running server uses (``<src>/signalweaver.db``).
    limit : int, optional
        Maximum number of records to return.  ``None`` = all matching rows.
    since : str, optional
        ISO-8601 date or datetime string.  Only return records created at or
        after this timestamp (UTC).  Accepts ``YYYY-MM-DD`` or full
        ``YYYY-MM-DDTHH:MM:SS`` format.
    until : str, optional
        ISO-8601 date or datetime string.  Only return records created
        strictly before this timestamp (UTC).

    Returns
    -------
    list[dict]
        Each dict contains the DecisionTrace scalar fields plus a parsed
        ``match_debug_json`` dict.  Compatible with all functions in
        ``phase2_shadow_analysis.py``.
    """
    if db_path is None:
        db_path = _default_db_path()

    engine = _make_engine(db_path)
    session_maker = sessionmaker(bind=engine)

    with session_maker() as session:
        return _query_shadow_records(session, limit=limit, since=since, until=until)


def _parse_dt(s: str) -> datetime:
    """Parse a date/datetime string into a timezone-aware datetime."""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    raise ValueError(
        f"Cannot parse datetime '{s}'. "
        "Expected format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS"
    )


def _query_shadow_records(
    session: Session,
    limit: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Execute the query and return records as dicts."""
    # Detect which columns actually exist in this DB schema.
    columns = _detect_columns(session)

    # Build the base query — use json_extract to filter shadow records.
    # json_extract returns 1 for true, 0 for false in SQLite.
    sql = f"""
        SELECT {', '.join(columns)}
        FROM decision_traces
        WHERE match_debug_json IS NOT NULL
          AND match_debug_json != ''
          AND json_extract(match_debug_json, '$.phase2_shadow.active') = 1
    """
    params: Dict[str, Any] = {}

    if since:
        sql += " AND created_at >= :since"
        # Store as ISO string for reliable TEXT comparison in SQLite
        params["since"] = _parse_dt(since).isoformat()

    if until:
        sql += " AND created_at < :until"
        params["until"] = _parse_dt(until).isoformat()

    sql += " ORDER BY created_at ASC"

    if limit is not None:
        sql += " LIMIT :limit"
        params["limit"] = limit

    try:
        rows = session.execute(text(sql), params).fetchall()
    except Exception:
        # Fallback: json_extract may not be available in older SQLite builds.
        # Pull all rows and filter in Python.
        rows = _fallback_query(session, columns, limit=limit, since=since, until=until)

    records = []
    for row in rows:
        rec = dict(zip(columns, row))
        # Pad with None for any columns missing from this schema.
        rec = _pad_record(rec, columns)
        # Parse match_debug_json from string to dict
        raw_md = rec.get("match_debug_json", "")
        if isinstance(raw_md, str) and raw_md:
            try:
                rec["match_debug_json"] = json.loads(raw_md)
            except (json.JSONDecodeError, TypeError):
                pass  # keep as-is
        # Serialise datetime for JSON output
        if isinstance(rec.get("created_at"), datetime):
            rec["created_at"] = rec["created_at"].isoformat()
        records.append(rec)

    return records


def _fallback_query(
    session: Session,
    columns: List[str],
    limit: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> list:
    """
    Fallback for SQLite builds without json_extract.
    Filters phase2_shadow.active in Python.
    """
    sql = f"SELECT {', '.join(columns)} FROM decision_traces WHERE match_debug_json IS NOT NULL AND match_debug_json != '' ORDER BY created_at ASC"
    params: Dict[str, Any] = {}

    if since:
        sql += " AND created_at >= :since"
        params["since"] = _parse_dt(since).isoformat()
    if until:
        sql += " AND created_at < :until"
        params["until"] = _parse_dt(until).isoformat()

    all_rows = session.execute(text(sql), params).fetchall()
    filtered = []
    for row in all_rows:
        rec = dict(zip(columns, row))
        raw = rec.get("match_debug_json", "")
        if not raw:
            continue
        try:
            md = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        shadow = md.get("phase2_shadow") if isinstance(md, dict) else None
        if isinstance(shadow, dict) and shadow.get("active") is True:
            # Pad before appending so _query_shadow_records sees the
            # same dict shape as the primary path.
            rec = _pad_record(rec, columns)
            filtered.append(tuple(rec[col] for col in columns))

    if limit is not None:
        filtered = filtered[:limit]

    return filtered


# ───────────────────────────────────────────────────────────────
# Write to file
# ───────────────────────────────────────────────────────────────


def write_traces_json(records: List[Dict[str, Any]], output_path: str | Path) -> Path:
    """
    Write exported records to a JSON file.

    Parameters
    ----------
    records : list[dict]
        Records returned by :func:`export_shadow_traces`.
    output_path : str or Path
        Destination file path.

    Returns
    -------
    Path
        The absolute path of the written file.
    """
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False, default=str)
    return output_path


# ───────────────────────────────────────────────────────────────
# Load exported JSON back
# ───────────────────────────────────────────────────────────────


def load_records_from_json(input_path: str | Path) -> List[Dict[str, Any]]:
    """
    Load records from a JSON file previously written by :func:`write_traces_json`.

    Returns a list of dicts compatible with ``phase2_shadow_analysis.py``.
    """
    input_path = Path(input_path).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"File not found: {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ───────────────────────────────────────────────────────────────
# Manual review pack generator
# ───────────────────────────────────────────────────────────────


def generate_review_pack(
    records: List[Dict[str, Any]],
    count: int = 20,
) -> List[Dict[str, Any]]:
    """
    Extract the most recent override cases into a compact format for manual
    review.

    For each record where ``would_change`` is non-empty, extract:

    - ``trace_id``              DecisionTrace row ID
    - ``created_at``            Timestamp
    - ``request_text``          Original request
    - ``decision``              Phase 1 decision (proceed/gate/refuse)
    - ``reason``                Phase 1 reason code
    - ``would_change``          Anchor IDs Phase 2 would flip
    - ``phase1_conflicts``      Phase 1 conflict set
    - ``phase2_conflicts``      Phase 2 conflict set
    - ``embedding_confidences`` Confidence values for would_change anchors
    - ``resolution_reasons``   Resolution reasons for would_change anchors
    - ``explanation``           Human-readable explanation

    Parameters
    ----------
    records : list[dict]
        Records from the analysis module or the exporter.
    count : int
        Maximum number of cases to include.  Defaults to 20.

    Returns
    -------
    list[dict]
        Override cases sorted newest-first, limited to *count*.
    """
    override_cases: List[Dict[str, Any]] = []

    for rec in records:
        md = rec.get("match_debug_json", {})
        if isinstance(md, str):
            try:
                md = json.loads(md)
            except (json.JSONDecodeError, TypeError):
                continue

        shadow = md.get("phase2_shadow")
        if not isinstance(shadow, dict) or not shadow.get("active"):
            continue

        would_change = shadow.get("would_change", [])
        if not would_change:
            continue

        # Extract embedding confidences and resolution reasons for
        # would_change anchors.
        confidences: Dict[int, float] = {}
        reasons: Dict[int, str] = {}
        for row in md.get("per_anchor_votes", []):
            aid = row.get("anchor_id")
            if aid not in would_change:
                continue
            reasons[aid] = row.get("resolution_reason", "")
            for vote in row.get("votes", []):
                if (vote.get("matcher") == "embedding"
                        and vote.get("verdict") == "conflict"):
                    confidences[aid] = float(vote.get("confidence", 0.0))

        override_cases.append({
            "trace_id": rec.get("id"),
            "created_at": rec.get("created_at"),
            "request_text": rec.get("request_text", ""),
            "decision": rec.get("decision", ""),
            "reason": rec.get("reason", ""),
            "explanation": rec.get("explanation", ""),
            "would_change": would_change,
            "phase1_conflicts": shadow.get("phase1_conflicts", []),
            "phase2_conflicts": shadow.get("phase2_conflicts", []),
            "embedding_confidences": {
                str(aid): conf for aid, conf in confidences.items()
            },
            "resolution_reasons": {
                str(aid): reason for aid, reason in reasons.items()
            },
        })

    # Sort newest-first (assuming created_at is ISO string or datetime).
    override_cases.sort(
        key=lambda c: c.get("created_at", ""),
        reverse=True,
    )
    return override_cases[:count]


# ───────────────────────────────────────────────────────────────
# CLI
# ───────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.analysis",
        description=(
            "SignalWeaver Phase 2 shadow data utilities: export traces, "
            "run analysis, generate review packs."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- export-shadow-traces ---
    p_export = sub.add_parser(
        "export-shadow-traces",
        help="Export DecisionTrace rows with phase2_shadow data to JSON.",
    )
    p_export.add_argument(
        "--output", "-o",
        default="traces.json",
        help="Output JSON file path (default: traces.json)",
    )
    p_export.add_argument(
        "--db",
        default=None,
        help="Path to SQLite database (default: <src>/signalweaver.db)",
    )
    p_export.add_argument(
        "--limit", "-n",
        type=int,
        default=None,
        help="Maximum records to export (default: all)",
    )
    p_export.add_argument(
        "--since",
        default=None,
        help="Only records at or after this timestamp (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)",
    )
    p_export.add_argument(
        "--until",
        default=None,
        help="Only records before this timestamp (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)",
    )

    # --- analyze ---
    p_analyze = sub.add_parser(
        "analyze",
        help="Run the full Phase 2 shadow analysis on an exported JSON file.",
    )
    p_analyze.add_argument(
        "--input", "-i",
        required=True,
        help="Path to JSON file exported by export-shadow-traces",
    )

    # --- review-pack ---
    p_review = sub.add_parser(
        "review-pack",
        help="Generate a compact manual review pack from exported traces.",
    )
    p_review.add_argument(
        "--input", "-i",
        default="traces.json",
        help="Path to JSON file exported by export-shadow-traces (default: traces.json)",
    )
    p_review.add_argument(
        "--output", "-o",
        default="review_pack.json",
        help="Output JSON file path (default: review_pack.json)",
    )
    p_review.add_argument(
        "--count", "-n",
        type=int,
        default=20,
        help="Maximum override cases to include (default: 20)",
    )

    return parser


def cli_main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point.  Returns an exit code (0 = success)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "export-shadow-traces":
        return _cmd_export(args)
    elif args.command == "analyze":
        return _cmd_analyze(args)
    elif args.command == "review-pack":
        return _cmd_review_pack(args)
    else:
        parser.print_help()
        return 1


def _cmd_export(args: argparse.Namespace) -> int:
    """Handle the export-shadow-traces sub-command."""
    try:
        print(f"Exporting shadow traces from database...")
        if args.db:
            print(f"  DB path: {args.db}")
        records = export_shadow_traces(
            db_path=args.db,
            limit=args.limit,
            since=args.since,
            until=args.until,
        )
        out = write_traces_json(records, args.output)
        print(f"  Exported {len(records)} shadow records to {out}")
        return 0
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def _cmd_analyze(args: argparse.Namespace) -> int:
    """Handle the analyze sub-command — run full analysis on exported data."""
    from app.analysis.phase2_shadow_analysis import summarize_phase2_shadow

    try:
        records = load_records_from_json(args.input)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    summary = summarize_phase2_shadow(records)

    # Print a concise report
    print("=" * 60)
    print("PHASE 2 SHADOW ANALYSIS REPORT")
    print("=" * 60)
    print(f"  Total records:          {summary['record_count']}")
    print(f"  Shadow records:         {summary['shadow_record_count']}")
    print(f"  Override rate:          {summary['override_rate']:.2%}")
    print(f"  Agreement rate:         {summary['agreement_rate']:.2%}")
    print(f"  Total overridden:       {summary['total_overridden_anchors']}")
    print(f"  Avg overrides/event:    {summary['avg_overrides_per_event']:.2f}")
    print(f"  Invariant violations:   {summary['invariant_violation_count']}")
    print()
    print("  Confidence histogram:")
    for bin_label, count in summary["confidence_histogram"].items():
        bar = "#" * count
        print(f"    {bin_label:16s} {count:4d}  {bar}")
    print()
    if summary["scope_distribution"]:
        print("  Scope distribution:")
        for scope, count in summary["scope_distribution"].items():
            print(f"    {scope:32s} {count}")
        print()
    if summary["invariant_violations_by_rule"]:
        print("  Invariant violations by rule:")
        for rule, count in summary["invariant_violations_by_rule"].items():
            print(f"    {rule:48s} {count}")
        print()

    print("=" * 60)
    return 0


def _cmd_review_pack(args: argparse.Namespace) -> int:
    """Handle the review-pack sub-command."""
    try:
        records = load_records_from_json(args.input)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    pack = generate_review_pack(records, count=args.count)
    out = write_traces_json(pack, args.output)
    print(f"Generated review pack with {len(pack)} override cases -> {out}")
    return 0