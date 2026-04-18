"""
test_export_shadow_traces.py — Tests for the Phase 2 shadow data exporter.

Covers:
  - Database query filtering (phase2_shadow.active)
  - JSON parsing of match_debug_json
  - Date range filtering (--since, --until)
  - Record limit
  - Fallback path for SQLite without json_extract
  - write_traces_json round-trip
  - load_records_from_json
  - generate_review_pack (override case extraction)
  - CLI entry points (export, analyze, review-pack)
  - Empty database (graceful)
  - Records without shadow data (excluded)
  - Backward-compatible schema detection (tenant_id absent)
  - Stable output shape across old and new schemas

Uses in-memory SQLite seeded with fabricated DecisionTrace rows.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

# Ensure imports resolve when running pytest from /src
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


# ───────────────────────────────────────────────────────────────
# Fixtures
# ───────────────────────────────────────────────────────────────


def _make_match_debug(
    has_shadow: bool = True,
    would_change: list | None = None,
    phase1_conflicts: list | None = None,
    phase2_conflicts: list | None = None,
    per_anchor: list | None = None,
) -> dict:
    """Build a match_debug dict, optionally with phase2_shadow."""
    md: dict = {
        "matcher_mode": "signals_v1",
        "evaluated_anchor_count": len(per_anchor or []),
        "conflicted_ids": list(phase1_conflicts or []),
        "per_anchor_votes": per_anchor or [],
    }
    if has_shadow:
        md["phase2_active"] = True
        md["phase2_threshold"] = 0.85
        md["phase2_shadow"] = {
            "active": True,
            "would_change": would_change or [],
            "phase1_conflicts": phase1_conflicts or [],
            "phase2_conflicts": phase2_conflicts or [],
        }
    return md


def _valid_wc_anchor(anchor_id: int = 10, confidence: float = 0.91) -> dict:
    """A valid would_change anchor row satisfying all invariants."""
    return {
        "anchor_id": anchor_id,
        "votes": [
            {"matcher": "naive", "verdict": "safe", "confidence": 1.0,
             "explanation": "safe_lockout"},
            {"matcher": "embedding", "verdict": "conflict",
             "confidence": confidence,
             "explanation": f"cosine similarity {confidence:.3f}"},
        ],
        "resolved": "safe",
        "resolution_reason": "safe_overrides_conflict",
    }


@pytest.fixture
def db_session():
    """Create an in-memory SQLite session seeded with test DecisionTrace rows."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE decision_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                policy_profile_id INTEGER,
                request_text TEXT DEFAULT '',
                request_normalized TEXT DEFAULT '',
                arousal TEXT DEFAULT 'unknown',
                dominance TEXT DEFAULT 'unknown',
                decision TEXT DEFAULT '',
                reason TEXT DEFAULT '',
                explanation TEXT DEFAULT '',
                match_debug_json TEXT DEFAULT '',
                would_block INTEGER DEFAULT 0,
                enforcement_mode_snapshot TEXT DEFAULT 'hard',
                override_reason TEXT DEFAULT '',
                tenant_id INTEGER
            )
        """))
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _insert_trace(
    session,
    trace_id: int = 1,
    created_at: str = "2025-06-01T10:00:00",
    request_text: str = "test request",
    decision: str = "proceed",
    reason: str = "no_conflicts",
    match_debug: dict | None = None,
    match_debug_json: str | None = None,
    explanation: str = "",
) -> None:
    """Insert a DecisionTrace row into the test database."""
    if match_debug_json is not None:
        md_json = match_debug_json
    else:
        md_json = json.dumps(match_debug, ensure_ascii=False) if match_debug else ""
    session.execute(text("""
        INSERT INTO decision_traces
            (id, created_at, request_text, decision, reason, explanation,
             match_debug_json, would_block, enforcement_mode_snapshot)
        VALUES
            (:id, :created_at, :request_text, :decision, :reason, :explanation,
             :match_debug_json, 0, 'hard')
    """), {
        "id": trace_id,
        "created_at": created_at,
        "request_text": request_text,
        "decision": decision,
        "reason": reason,
        "explanation": explanation,
        "match_debug_json": md_json,
    })
    session.commit()


def _seed_standard_data(session) -> list:
    """
    Seed the DB with 5 records: 3 shadow, 1 no-shadow, 1 empty match_debug.
    Returns the list of inserted trace IDs.
    """
    now = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
    ids = []
    for i in range(3):
        t = now + timedelta(hours=i)
        per_anchor = [
            _valid_wc_anchor(anchor_id=10 + i, confidence=0.88 + i * 0.03),
            {
                "anchor_id": 3 + i,
                "votes": [{"matcher": "naive", "verdict": "conflict",
                            "confidence": 1.0}],
                "resolved": "conflict",
                "resolution_reason": "conflict_no_safe",
            },
        ]
        md = _make_match_debug(
            has_shadow=True,
            would_change=[10 + i],
            phase1_conflicts=[3 + i],
            phase2_conflicts=[3 + i, 10 + i],
            per_anchor=per_anchor,
        )
        _insert_trace(
            session,
            trace_id=i + 1,
            created_at=t.isoformat(),
            request_text=f"request {i+1}",
            decision="gate",
            reason="conflicts_detected",
            match_debug=md,
            explanation=f"Conflicts with anchors {[3+i]}",
        )
        ids.append(i + 1)

    # Record 4: no shadow data
    md_no_shadow = _make_match_debug(has_shadow=False)
    _insert_trace(
        session, trace_id=4,
        created_at=(now + timedelta(hours=3)).isoformat(),
        request_text="no shadow request",
        decision="proceed",
        match_debug=md_no_shadow,
    )
    ids.append(4)

    # Record 5: empty match_debug_json
    _insert_trace(
        session, trace_id=5,
        created_at=(now + timedelta(hours=4)).isoformat(),
        request_text="empty match debug",
        decision="proceed",
        match_debug_json="",
    )
    _insert_trace(
        session, trace_id=6,
        created_at=(now + timedelta(hours=4)).isoformat(),
        request_text="empty match debug 2",
        decision="proceed",
    )
    ids.append(5)

    return ids


# ───────────────────────────────────────────────────────────────
# Import the module under test
# ───────────────────────────────────────────────────────────────

from app.analysis.export_shadow_traces import (
    export_shadow_traces,
    write_traces_json,
    load_records_from_json,
    generate_review_pack,
    cli_main,
    _query_shadow_records,
    _parse_dt,
    _detect_columns,
    _pad_record,
    _FULL_COLUMNS,
)


# ───────────────────────────────────────────────────────────────
# 1. Core export — filtering
# ───────────────────────────────────────────────────────────────


class TestExportFiltering:

    def test_only_shadow_records_exported(self, db_session):
        """Records without phase2_shadow.active=true should be excluded."""
        _seed_standard_data(db_session)
        records = _query_shadow_records(db_session)
        assert len(records) == 3
        for rec in records:
            md = rec["match_debug_json"]
            assert md["phase2_shadow"]["active"] is True

    def test_no_shadow_records(self, db_session):
        """Empty DB returns empty list."""
        records = _query_shadow_records(db_session)
        assert records == []

    def test_match_debug_json_parsed(self, db_session):
        """match_debug_json should be a parsed dict, not a string."""
        _seed_standard_data(db_session)
        records = _query_shadow_records(db_session)
        for rec in records:
            assert isinstance(rec["match_debug_json"], dict)
            assert "phase2_shadow" in rec["match_debug_json"]

    def test_scalar_fields_present(self, db_session):
        """Each record should have all DecisionTrace scalar fields."""
        _seed_standard_data(db_session)
        records = _query_shadow_records(db_session)
        for rec in records:
            assert set(_FULL_COLUMNS).issubset(set(rec.keys()))

    def test_tenant_id_present_in_new_schema(self, db_session):
        """New-schema DB should include real tenant_id values."""
        _insert_trace(
            db_session, trace_id=1,
            match_debug=_make_match_debug(
                has_shadow=True, would_change=[1],
                phase1_conflicts=[], phase2_conflicts=[1],
                per_anchor=[_valid_wc_anchor(1)],
            ),
        )
        # Explicitly set tenant_id via a raw UPDATE
        db_session.execute(text(
            "UPDATE decision_traces SET tenant_id = 42 WHERE id = 1"
        ))
        db_session.commit()
        records = _query_shadow_records(db_session)
        assert len(records) == 1
        assert records[0]["tenant_id"] == 42


# ───────────────────────────────────────────────────────────────
# 2. Date range filtering
# ───────────────────────────────────────────────────────────────


class TestDateFiltering:

    def test_since_filter(self, db_session):
        """--since should exclude records before the timestamp."""
        _seed_standard_data(db_session)
        # Records at 10:00, 11:00, 12:00, 13:00, 14:00
        records = _query_shadow_records(
            db_session, since="2025-06-01T12:00:00"
        )
        assert len(records) == 1
        assert records[0]["id"] == 3

    def test_until_filter(self, db_session):
        """--until should exclude records at or after the timestamp."""
        _seed_standard_data(db_session)
        records = _query_shadow_records(
            db_session, until="2025-06-01T12:00:00"
        )
        # Records 1 and 2 are at 10:00 and 11:00 (< 12:00)
        assert len(records) == 2
        assert records[0]["id"] == 1
        assert records[1]["id"] == 2

    def test_date_only_since(self, db_session):
        """--since with date-only (YYYY-MM-DD) should work."""
        _seed_standard_data(db_session)
        # All records are on 2025-06-01
        records = _query_shadow_records(
            db_session, since="2025-06-01"
        )
        assert len(records) == 3

    def test_date_only_until(self, db_session):
        """--until with date-only should use start-of-day."""
        _seed_standard_data(db_session)
        records = _query_shadow_records(
            db_session, until="2025-06-02"
        )
        assert len(records) == 3


# ───────────────────────────────────────────────────────────────
# 3. Limit
# ───────────────────────────────────────────────────────────────


class TestLimit:

    def test_limit_respected(self, db_session):
        """--limit should cap the number of returned records."""
        _seed_standard_data(db_session)
        records = _query_shadow_records(db_session, limit=2)
        assert len(records) == 2
        # Should be the 2 earliest (ASC order)
        assert records[0]["id"] == 1
        assert records[1]["id"] == 2

    def test_limit_larger_than_total(self, db_session):
        """Limit larger than matching rows returns all."""
        _seed_standard_data(db_session)
        records = _query_shadow_records(db_session, limit=100)
        assert len(records) == 3

    def test_limit_one(self, db_session):
        records = _query_shadow_records(db_session, limit=1)
        assert len(records) <= 1


# ───────────────────────────────────────────────────────────────
# 4. Fallback query (no json_extract)
# ───────────────────────────────────────────────────────────────


class TestFallback:

    def test_fallback_filters_shadow(self, db_session):
        """Python-side fallback should also correctly filter shadow records."""
        _seed_standard_data(db_session)
        columns = [
            "id", "created_at", "request_text", "decision", "reason",
            "explanation", "match_debug_json", "arousal", "dominance",
            "enforcement_mode_snapshot", "would_block", "override_reason",
        ]
        from app.analysis.export_shadow_traces import _fallback_query
        rows = _fallback_query(db_session, columns)
        assert len(rows) == 3


# ───────────────────────────────────────────────────────────────
# 5. write_traces_json / load_records_from_json
# ───────────────────────────────────────────────────────────────


class TestJsonRoundTrip:

    def test_write_and_load(self, db_session):
        """Write to file and load back — data should match."""
        _seed_standard_data(db_session)
        records = _query_shadow_records(db_session)

        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            tmp_path = f.name

        try:
            out = write_traces_json(records, tmp_path)
            assert Path(out).exists()

            loaded = load_records_from_json(out)
            assert len(loaded) == len(records)
            for orig, loaded_rec in zip(records, loaded):
                assert loaded_rec["id"] == orig["id"]
                assert loaded_rec["match_debug_json"] == orig["match_debug_json"]
        finally:
            os.unlink(tmp_path)

    def test_load_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            load_records_from_json("/nonexistent/path/traces.json")

    def test_write_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "a", "b", "traces.json")
            out = write_traces_json([], nested)
            assert Path(out).exists()

    def test_output_valid_json(self, db_session):
        """Output must be valid JSON parseable by json.load."""
        _seed_standard_data(db_session)
        records = _query_shadow_records(db_session)
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            tmp_path = f.name
        try:
            write_traces_json(records, tmp_path)
            with open(tmp_path) as f:
                data = json.load(f)
            assert isinstance(data, list)
            assert len(data) == 3
        finally:
            os.unlink(tmp_path)


# ───────────────────────────────────────────────────────────────
# 6. generate_review_pack
# ───────────────────────────────────────────────────────────────


class TestReviewPack:

    def _make_records(self) -> list:
        """Create records matching the analysis module input format."""
        records = []
        for i in range(5):
            per_anchor = [
                _valid_wc_anchor(anchor_id=10 + i, confidence=0.88 + i * 0.02),
            ]
            if i < 3:
                md = _make_match_debug(
                    has_shadow=True,
                    would_change=[10 + i],
                    phase1_conflicts=[],
                    phase2_conflicts=[10 + i],
                    per_anchor=per_anchor,
                )
            else:
                # No override
                md = _make_match_debug(
                    has_shadow=True,
                    would_change=[],
                    phase1_conflicts=[],
                    phase2_conflicts=[],
                    per_anchor=per_anchor,
                )
            records.append({
                "id": 100 + i,
                "created_at": f"2025-06-{10 + i:02d}T10:00:00",
                "request_text": f"request {i}",
                "decision": "gate",
                "reason": "conflicts_detected",
                "explanation": f"some explanation {i}",
                "match_debug_json": md,
            })
        return records

    def test_only_override_cases_included(self):
        """Review pack should only contain records with non-empty would_change."""
        records = self._make_records()
        pack = generate_review_pack(records)
        # First 3 have overrides, last 2 don't
        assert len(pack) == 3

    def test_sorted_newest_first(self):
        """Review pack should be sorted by created_at descending."""
        records = self._make_records()
        pack = generate_review_pack(records)
        timestamps = [c["created_at"] for c in pack]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_count_limit(self):
        """--count should limit the number of cases."""
        records = self._make_records()
        pack = generate_review_pack(records, count=2)
        assert len(pack) == 2

    def test_pack_fields_present(self):
        """Each review case should have all expected fields."""
        records = self._make_records()
        pack = generate_review_pack(records, count=1)
        case = pack[0]
        expected_keys = {
            "trace_id", "created_at", "request_text", "decision", "reason",
            "explanation", "would_change", "phase1_conflicts",
            "phase2_conflicts", "embedding_confidences", "resolution_reasons",
        }
        assert expected_keys.issubset(set(case.keys()))

    def test_embedding_confidences_extracted(self):
        """Embedding confidence values should be keyed by anchor_id (str)."""
        records = self._make_records()
        pack = generate_review_pack(records, count=1)
        case = pack[0]
        aid = str(case["would_change"][0])
        assert aid in case["embedding_confidences"]
        assert case["embedding_confidences"][aid] > 0

    def test_empty_records(self):
        """Empty input should return empty pack."""
        assert generate_review_pack([]) == []

    def test_no_override_records(self):
        """Records with shadow active but no overrides should give empty pack."""
        records = [{
            "id": 1,
            "created_at": "2025-06-01T10:00:00",
            "request_text": "test",
            "decision": "proceed",
            "match_debug_json": _make_match_debug(
                has_shadow=True, would_change=[],
            ),
        }]
        assert generate_review_pack(records) == []


# ───────────────────────────────────────────────────────────────
# 7. CLI sub-commands
# ───────────────────────────────────────────────────────────────


class TestCLI:

    def test_export_help(self):
        """CLI should not crash on --help."""
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["export-shadow-traces", "--help"])
        assert exc_info.value.code == 0

    def test_analyze_help(self):
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["analyze", "--help"])
        assert exc_info.value.code == 0

    def test_review_pack_help(self):
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["review-pack", "--help"])
        assert exc_info.value.code == 0

    def test_no_command(self):
        """No sub-command should print help and exit 1."""
        with pytest.raises(SystemExit) as exc_info:
            cli_main([])
        assert exc_info.value.code == 2

    def test_analyze_missing_file(self, capsys):
        """Analyze with nonexistent file should print error."""
        rc = cli_main(["analyze", "--input", "/nonexistent/traces.json"])
        assert rc == 1
        assert "ERROR" in capsys.readouterr().err

    def test_review_pack_missing_file(self, capsys):
        rc = cli_main(["review-pack", "--input", "/nonexistent/traces.json"])
        assert rc == 1
        assert "ERROR" in capsys.readouterr().err

    def test_export_missing_db(self, capsys):
        """Export with nonexistent DB should print error."""
        rc = cli_main([
            "export-shadow-traces",
            "--db", "/nonexistent/test.db",
            "--output", "/tmp/out.json",
        ])
        assert rc == 1
        assert "ERROR" in capsys.readouterr().err

    def test_analyze_with_real_data(self, capsys):
        """Analyze should print a report when given valid input."""
        records = [{
            "id": 1,
            "created_at": "2025-06-01T10:00:00",
            "request_text": "test",
            "decision": "gate",
            "reason": "conflicts",
            "explanation": "test",
            "match_debug_json": _make_match_debug(
                has_shadow=True,
                would_change=[10],
                phase1_conflicts=[],
                phase2_conflicts=[10],
                per_anchor=[_valid_wc_anchor(10, 0.91)],
            ),
        }]
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            json.dump(records, f)
            tmp_path = f.name
        try:
            rc = cli_main(["analyze", "--input", tmp_path])
            assert rc == 0
            output = capsys.readouterr().out
            assert "PHASE 2 SHADOW ANALYSIS REPORT" in output
            assert "Override rate" in output
            assert "Agreement rate" in output
            assert "Confidence histogram" in output
        finally:
            os.unlink(tmp_path)

    def test_review_pack_with_real_data(self, capsys):
        """Review-pack should produce output file and print summary."""
        records = [{
            "id": 1,
            "created_at": "2025-06-01T10:00:00",
            "request_text": "test request",
            "decision": "gate",
            "reason": "conflicts",
            "explanation": "test explanation",
            "match_debug_json": _make_match_debug(
                has_shadow=True,
                would_change=[10],
                phase1_conflicts=[],
                phase2_conflicts=[10],
                per_anchor=[_valid_wc_anchor(10, 0.91)],
            ),
        }]
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            json.dump(records, f)
            input_path = f.name
        output_path = input_path + ".review.json"
        try:
            rc = cli_main([
                "review-pack",
                "--input", input_path,
                "--output", output_path,
                "--count", "5",
            ])
            assert rc == 0
            assert Path(output_path).exists()
            output = capsys.readouterr().out
            assert "review pack" in output.lower()
            with open(output_path) as f:
                pack = json.load(f)
            assert len(pack) == 1
            assert "would_change" in pack[0]
        finally:
            os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)


# ───────────────────────────────────────────────────────────────
# 8. Integration: full pipeline
# ───────────────────────────────────────────────────────────────


class TestFullPipeline:

    def test_export_then_analyze(self, db_session, capsys):
        """Export traces from DB, write to file, then run analysis."""
        _seed_standard_data(db_session)
        records = _query_shadow_records(db_session)

        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            json.dump(records, f)
            tmp_path = f.name

        try:
            # Run analyze on the exported data
            from app.analysis.phase2_shadow_analysis import (
                summarize_phase2_shadow,
            )
            summary = summarize_phase2_shadow(records)
            assert summary["record_count"] == 3
            assert summary["shadow_record_count"] == 3
            assert summary["override_rate"] == pytest.approx(1.0)
            assert len(summary["override_confidences"]) == 3

            # Verify via CLI
            rc = cli_main(["analyze", "--input", tmp_path])
            assert rc == 0
            output = capsys.readouterr().out
            assert "PHASE 2 SHADOW ANALYSIS REPORT" in output
        finally:
            os.unlink(tmp_path)

    def test_export_then_review_pack(self, db_session):
        """Export traces, then generate review pack."""
        _seed_standard_data(db_session)
        records = _query_shadow_records(db_session)
        pack = generate_review_pack(records)
        assert len(pack) == 3  # all have overrides


# ───────────────────────────────────────────────────────────────
# 9. Old-schema DB (no tenant_id)
# ───────────────────────────────────────────────────────────────


_OLD_SCHEMA_DDL = """
    CREATE TABLE decision_traces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT,
        policy_profile_id INTEGER,
        request_text TEXT DEFAULT '',
        request_normalized TEXT DEFAULT '',
        arousal TEXT DEFAULT 'unknown',
        dominance TEXT DEFAULT 'unknown',
        decision TEXT DEFAULT '',
        reason TEXT DEFAULT '',
        explanation TEXT DEFAULT '',
        match_debug_json TEXT DEFAULT '',
        would_block INTEGER DEFAULT 0,
        enforcement_mode_snapshot TEXT DEFAULT 'hard',
        override_reason TEXT DEFAULT ''
    )
"""


@pytest.fixture
def old_schema_db_session():
    """In-memory SQLite WITHOUT tenant_id column."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as conn:
        conn.execute(text(_OLD_SCHEMA_DDL))
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestOldSchema:

    def _seed_old(self, session):
        """Insert shadow records into an old-schema DB."""
        now = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
        for i in range(2):
            t = now + timedelta(hours=i)
            md = _make_match_debug(
                has_shadow=True,
                would_change=[10 + i],
                phase1_conflicts=[],
                phase2_conflicts=[10 + i],
                per_anchor=[_valid_wc_anchor(10 + i, 0.90 + i * 0.05)],
            )
            _insert_trace(
                session,
                trace_id=i + 1,
                created_at=t.isoformat(),
                request_text=f"old schema request {i}",
                decision="gate",
                reason="conflicts_detected",
                match_debug=md,
                explanation=f"Conflicts with anchor {10 + i}",
            )

    def test_detect_columns_excludes_tenant_id(self, old_schema_db_session):
        """_detect_columns should NOT include tenant_id on old schema."""
        cols = _detect_columns(old_schema_db_session)
        assert "tenant_id" not in cols
        assert "id" in cols
        assert "match_debug_json" in cols

    def test_export_succeeds_on_old_schema(self, old_schema_db_session):
        """Exporter should not fail when tenant_id is absent."""
        self._seed_old(old_schema_db_session)
        records = _query_shadow_records(old_schema_db_session)
        assert len(records) == 2

    def test_old_schema_records_have_tenant_id_null(self, old_schema_db_session):
        """Exported records from old schema must include tenant_id: None."""
        self._seed_old(old_schema_db_session)
        records = _query_shadow_records(old_schema_db_session)
        for rec in records:
            assert "tenant_id" in rec
            assert rec["tenant_id"] is None

    def test_old_schema_output_shape_stable(self, old_schema_db_session):
        """Old-schema records must have the same keys as new-schema records."""
        self._seed_old(old_schema_db_session)
        records = _query_shadow_records(old_schema_db_session)
        for rec in records:
            assert set(rec.keys()) == set(_FULL_COLUMNS)

    def test_old_schema_shadow_filtering(self, old_schema_db_session):
        """Only shadow records should be returned even on old schema."""
        self._seed_old(old_schema_db_session)
        # Add a non-shadow record
        _insert_trace(
            old_schema_db_session, trace_id=99,
            request_text="no shadow",
            match_debug=_make_match_debug(has_shadow=False),
        )
        records = _query_shadow_records(old_schema_db_session)
        assert len(records) == 2
        assert all(r["id"] != 99 for r in records)

    def test_old_schema_date_filtering(self, old_schema_db_session):
        """Date filtering should work on old-schema DB."""
        self._seed_old(old_schema_db_session)
        # Records at 10:00, 11:00 — since 11:00 should match record 2
        records = _query_shadow_records(
            old_schema_db_session, since="2025-06-01T11:00:00"
        )
        assert len(records) == 1
        assert records[0]["id"] == 2

    def test_old_schema_limit(self, old_schema_db_session):
        """Limit should work on old-schema DB."""
        self._seed_old(old_schema_db_session)
        records = _query_shadow_records(old_schema_db_session, limit=1)
        assert len(records) == 1

    def test_old_schema_cli_export(self, old_schema_db_session, capsys):
        """CLI export-shadow-traces should succeed against old schema."""
        self._seed_old(old_schema_db_session)
        # We cannot easily pass an in-memory DB path to the CLI,
        # so test the lower-level export_shadow_traces function instead.
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker as sm

        # Create a file-backed old-schema DB for the CLI
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "old_schema.db")
            engine = create_engine(f"sqlite:///{db_path}")
            with engine.begin() as conn:
                conn.execute(text(_OLD_SCHEMA_DDL))
            Session = sm(bind=engine)
            session = Session()
            try:
                for i in range(2):
                    md = _make_match_debug(
                        has_shadow=True,
                        would_change=[10 + i],
                        phase1_conflicts=[],
                        phase2_conflicts=[10 + i],
                        per_anchor=[_valid_wc_anchor(10 + i)],
                    )
                    _insert_trace(
                        session, trace_id=i + 1,
                        request_text=f"cli test {i}",
                        match_debug=md,
                    )
                output_path = os.path.join(tmpdir, "traces.json")
                records = export_shadow_traces(db_path=db_path)
                assert len(records) == 2
                for rec in records:
                    assert rec["tenant_id"] is None
                    assert set(rec.keys()) == set(_FULL_COLUMNS)
                # Also test write_traces_json round-trip
                out = write_traces_json(records, output_path)
                loaded = load_records_from_json(out)
                assert len(loaded) == 2
                assert loaded[0]["tenant_id"] is None
            finally:
                session.close()

    def test_old_schema_review_pack_compatible(self, old_schema_db_session):
        """Review pack should work on records exported from old-schema DB."""
        self._seed_old(old_schema_db_session)
        records = _query_shadow_records(old_schema_db_session)
        pack = generate_review_pack(records)
        assert len(pack) == 2
        for case in pack:
            assert "would_change" in case
            assert len(case["would_change"]) == 1

    def test_old_schema_fallback_query(self, old_schema_db_session):
        """Fallback query should work on old schema."""
        self._seed_old(old_schema_db_session)
        cols = _detect_columns(old_schema_db_session)
        from app.analysis.export_shadow_traces import _fallback_query
        rows = _fallback_query(old_schema_db_session, cols)
        assert len(rows) >= 2

    def test_old_schema_analysis_module_compatible(self, old_schema_db_session):
        """Records from old schema must be compatible with analysis module."""
        from app.analysis.phase2_shadow_analysis import (
            compute_override_rate,
            check_invariants,
        )
        self._seed_old(old_schema_db_session)
        records = _query_shadow_records(old_schema_db_session)
        rate = compute_override_rate(records)
        assert rate == 1.0
        violations = check_invariants(records)
        assert len(violations) == 0


class TestSchemaDetection:

    def test_new_schema_detection(self, db_session):
        """_detect_columns returns all columns on new schema."""
        cols = _detect_columns(db_session)
        assert "tenant_id" in cols
        assert len(cols) == len(_FULL_COLUMNS)

    def test_old_schema_detection(self, old_schema_db_session):
        """_detect_columns excludes tenant_id on old schema."""
        cols = _detect_columns(old_schema_db_session)
        assert "tenant_id" not in cols
        assert len(cols) == len(_FULL_COLUMNS) - 1

    def test_pad_record_adds_missing_keys(self):
        """_pad_record should add missing columns with None."""
        rec = {"id": 1, "decision": "proceed"}
        padded = _pad_record(rec, [])
        for col in _FULL_COLUMNS:
            assert col in padded
        assert padded["tenant_id"] is None
        assert padded["id"] == 1
        assert padded["decision"] == "proceed"

    def test_pad_record_idempotent(self):
        """Calling _pad_record twice should not change the result."""
        rec = {"id": 1, "tenant_id": 99}
        padded1 = _pad_record(rec, [])
        padded2 = _pad_record(padded1, [])
        assert padded1 == padded2

    def test_full_columns_constant(self):
        """_FULL_COLUMNS must include tenant_id and all expected fields."""
        expected = {
            "id", "created_at", "policy_profile_id", "request_text",
            "request_normalized", "arousal", "dominance", "decision",
            "reason", "explanation", "match_debug_json", "would_block",
            "enforcement_mode_snapshot", "override_reason", "tenant_id",
        }
        assert set(_FULL_COLUMNS) == expected


# ───────────────────────────────────────────────────────────────
# 10. Edge cases
# ───────────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_malformed_json_in_db(self, db_session):
        """Rows with invalid JSON in match_debug_json should be skipped."""
        _insert_trace(
            db_session, trace_id=1,
            match_debug_json="{invalid json",
        )
        _insert_trace(
            db_session, trace_id=2,
            match_debug_json=json.dumps(_make_match_debug(
                has_shadow=True, would_change=[1],
                phase1_conflicts=[], phase2_conflicts=[1],
                per_anchor=[_valid_wc_anchor(1)],
            )),
        )
        records = _query_shadow_records(db_session)
        # Only record 2 should be returned (valid JSON with shadow)
        assert len(records) == 1
        assert records[0]["id"] == 2

    def test_shadow_inactive(self, db_session):
        """phase2_shadow.active=false should be excluded."""
        md = _make_match_debug(has_shadow=False)
        md["phase2_shadow"] = {"active": False, "would_change": [1]}
        _insert_trace(
            db_session, trace_id=1,
            match_debug_json=json.dumps(md),
        )
        records = _query_shadow_records(db_session)
        assert len(records) == 0

    def test_empty_would_change_included(self):
        """Shadow records with empty would_change should still be exported."""
        rec = {
            "id": 1,
            "created_at": "2025-06-01T10:00:00",
            "request_text": "test",
            "decision": "proceed",
            "reason": "",
            "explanation": "",
            "match_debug_json": _make_match_debug(
                has_shadow=True, would_change=[],
            ),
        }
        pack = generate_review_pack([rec])
        # No overrides -> not in review pack
        assert pack == []

    def test_parse_dt_formats(self):
        """_parse_dt should handle date-only and datetime strings."""
        dt1 = _parse_dt("2025-06-01")
        assert dt1.year == 2025
        assert dt1.month == 6
        assert dt1.day == 1
        assert dt1.tzinfo is not None

        dt2 = _parse_dt("2025-06-01T12:30:00")
        assert dt2.hour == 12
        assert dt2.minute == 30

    def test_parse_dt_invalid(self):
        with pytest.raises(ValueError):
            _parse_dt("not-a-date")

    def test_records_compatible_with_analysis_module(self, db_session):
        """Exported records must be directly usable by analysis functions."""
        from app.analysis.phase2_shadow_analysis import (
            compute_override_rate,
            compute_agreement_rate,
            check_invariants,
        )
        _seed_standard_data(db_session)
        records = _query_shadow_records(db_session)

        # All analysis functions should work without errors
        rate = compute_override_rate(records)
        assert rate > 0

        agreement = compute_agreement_rate(records)
        assert 0 <= agreement <= 1

        violations = check_invariants(records)
        assert isinstance(violations, list)