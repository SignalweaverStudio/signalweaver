"""
test_phase2_shadow_analysis.py â€” Tests for the Phase 2 shadow analysis
offline utility.

Covers:
  - Empty / no-shadow inputs (graceful degradation)
  - Override rate with mixed records
  - Override counts (total + average)
  - Agreement rate (P1 == P2)
  - Confidence extraction for would_change anchors
  - Confidence histogram binning
  - Invariant violations (all five rules)
  - Scope distribution (present and absent)
  - summarizePhase2Shadow aggregation
  - JSON-encoded match_debug_json handling

No DB dependency.  Pure dict-based test records.
"""

from __future__ import annotations

import json

import pytest

from app.analysis.phase2_shadow_analysis import (
    compute_agreement_rate,
    compute_confidence_histogram,
    compute_override_counts,
    compute_override_rate,
    compute_scope_distribution,
    check_invariants,
    extract_override_confidences,
    summarize_phase2_shadow,
)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Test-data helpers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _vote(matcher: str, verdict: str, confidence: float,
          explanation: str = "") -> dict:
    return {
        "matcher": matcher,
        "verdict": verdict,
        "confidence": confidence,
        "explanation": explanation,
    }


def _anchor_row(
    anchor_id: int,
    votes: list,
    resolved: str = "conflict",
    resolution_reason: str = "",
    scope: str | None = None,
) -> dict:
    row: dict = {
        "anchor_id": anchor_id,
        "votes": votes,
        "resolved": resolved,
        "resolution_reason": resolution_reason,
    }
    if scope is not None:
        row["scope"] = scope
    return row


def _shadow_record(
    would_change: list[int],
    phase1_conflicts: list[int],
    phase2_conflicts: list[int],
    per_anchor: list[dict],
    phase2_threshold: float = 0.85,
) -> dict:
    """Build a record whose match_debug_json contains valid shadow data."""
    return {
        "match_debug_json": {
            "matcher_mode": "signals_v1",
            "evaluated_anchor_count": len(per_anchor),
            "conflicted_ids": list(phase1_conflicts),
            "per_anchor_votes": per_anchor,
            "phase2_active": True,
            "phase2_threshold": phase2_threshold,
            "phase2_shadow": {
                "active": True,
                "would_change": would_change,
                "phase1_conflicts": list(phase1_conflicts),
                "phase2_conflicts": list(phase2_conflicts),
            },
        },
    }


def _no_shadow_record(match_debug: dict | None = None) -> dict:
    """Build a record with no phase2_shadow data."""
    md = match_debug or {
        "matcher_mode": "signals_v1",
        "evaluated_anchor_count": 0,
        "conflicted_ids": [],
        "per_anchor_votes": [],
    }
    return {"match_debug_json": md}


# A "canonical" would_change anchor row that satisfies all invariants.
# Phase 1 resolution: safe_overrides_conflict (safe + conflict, Phase 1)
# Embedding conflict at 0.91 >= 0.85 threshold.
def _valid_wc_row(
    anchor_id: int = 10,
    confidence: float = 0.91,
    threshold: float = 0.85,
    scope: str | None = None,
) -> dict:
    return _anchor_row(
        anchor_id=anchor_id,
        votes=[
            _vote("naive", "safe", 1.0, "safe_lockout detected"),
            _vote("embedding", "conflict", confidence,
                  f"cosine similarity {confidence:.3f}"),
        ],
        resolved="safe",
        resolution_reason="safe_overrides_conflict",
        scope=scope,
    )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 1. No shadow data â†’ graceful zeros
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestNoShadowData:

    def test_empty_list(self):
        assert compute_override_rate([]) == 0.0
        assert compute_agreement_rate([]) == 0.0
        assert extract_override_confidences([]) == []
        assert compute_override_counts([]) == {
            "total_overridden_anchors": 0,
            "avg_overrides_per_event": 0.0,
            "shadow_record_count": 0,
        }

    def test_records_without_shadow(self):
        records = [_no_shadow_record() for _ in range(5)]
        assert compute_override_rate(records) == 0.0
        assert compute_agreement_rate(records) == 0.0
        assert extract_override_confidences(records) == []

    def test_records_with_shadow_inactive(self):
        """phase2_shadow.active=False should be treated as no shadow."""
        rec = {
            "match_debug_json": {
                "phase2_shadow": {"active": False, "would_change": [1]},
            },
        }
        assert compute_override_rate([rec]) == 0.0

    def test_summarize_empty(self):
        s = summarize_phase2_shadow([])
        assert s["record_count"] == 0
        assert s["shadow_record_count"] == 0
        assert s["override_rate"] == 0.0
        assert s["invariant_violation_count"] == 0

    def test_summarize_no_shadow(self):
        records = [_no_shadow_record(), _no_shadow_record()]
        s = summarize_phase2_shadow(records)
        assert s["record_count"] == 2
        assert s["shadow_record_count"] == 0


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 2. Override rate
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestOverrideRate:

    def test_all_overridden(self):
        rec = _shadow_record(
            would_change=[10],
            phase1_conflicts=[3],
            phase2_conflicts=[3, 10],
            per_anchor=[_valid_wc_row(10), _anchor_row(3, [_vote("naive", "conflict", 1.0)], "conflict", "conflict_no_safe")],
        )
        assert compute_override_rate([rec, rec]) == 1.0

    def test_none_overridden(self):
        rec = _shadow_record(
            would_change=[],
            phase1_conflicts=[3],
            phase2_conflicts=[3],
            per_anchor=[_anchor_row(3, [_vote("naive", "conflict", 1.0)], "conflict", "conflict_no_safe")],
        )
        assert compute_override_rate([rec]) == 0.0

    def test_mixed(self):
        overridden = _shadow_record(
            would_change=[1],
            phase1_conflicts=[2],
            phase2_conflicts=[1, 2],
            per_anchor=[_valid_wc_row(1), _anchor_row(2, [_vote("naive", "conflict", 1.0)], "conflict", "conflict_no_safe")],
        )
        not_overridden = _shadow_record(
            would_change=[],
            phase1_conflicts=[5],
            phase2_conflicts=[5],
            per_anchor=[_anchor_row(5, [_vote("naive", "conflict", 1.0)], "conflict", "conflict_no_safe")],
        )
        rate = compute_override_rate([overridden, not_overridden])
        assert rate == pytest.approx(0.5)

    def test_non_shadow_ignored_in_denominator(self):
        """Records without shadow should not affect the rate."""
        shadow = _shadow_record(
            would_change=[1],
            phase1_conflicts=[],
            phase2_conflicts=[1],
            per_anchor=[_valid_wc_row(1)],
        )
        no_shadow = _no_shadow_record()
        rate = compute_override_rate([shadow, no_shadow, no_shadow])
        assert rate == 1.0


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 3. Override counts
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestOverrideCounts:

    def test_single(self):
        rec = _shadow_record(
            would_change=[10, 20],
            phase1_conflicts=[],
            phase2_conflicts=[10, 20],
            per_anchor=[_valid_wc_row(10), _valid_wc_row(20)],
        )
        counts = compute_override_counts([rec])
        assert counts["total_overridden_anchors"] == 2
        assert counts["avg_overrides_per_event"] == pytest.approx(2.0)
        assert counts["shadow_record_count"] == 1

    def test_multiple(self):
        r1 = _shadow_record(
            would_change=[1], phase1_conflicts=[],
            phase2_conflicts=[1], per_anchor=[_valid_wc_row(1)],
        )
        r2 = _shadow_record(
            would_change=[2, 3], phase1_conflicts=[],
            phase2_conflicts=[2, 3],
            per_anchor=[_valid_wc_row(2), _valid_wc_row(3)],
        )
        counts = compute_override_counts([r1, r2])
        assert counts["total_overridden_anchors"] == 3
        assert counts["avg_overrides_per_event"] == pytest.approx(1.5)
        assert counts["shadow_record_count"] == 2

    def test_non_shadow_excluded(self):
        shadow = _shadow_record(
            would_change=[1], phase1_conflicts=[],
            phase2_conflicts=[1], per_anchor=[_valid_wc_row(1)],
        )
        counts = compute_override_counts([shadow, _no_shadow_record()])
        assert counts["total_overridden_anchors"] == 1
        assert counts["shadow_record_count"] == 1


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 4. Agreement rate
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestAgreementRate:

    def test_full_agreement(self):
        rec = _shadow_record(
            would_change=[],
            phase1_conflicts=[1, 2],
            phase2_conflicts=[1, 2],
            per_anchor=[
                _anchor_row(1, [_vote("naive", "conflict", 1.0)], "conflict", "conflict_no_safe"),
                _anchor_row(2, [_vote("naive", "conflict", 1.0)], "conflict", "conflict_no_safe"),
            ],
        )
        assert compute_agreement_rate([rec]) == 1.0

    def test_no_agreement(self):
        rec = _shadow_record(
            would_change=[3],
            phase1_conflicts=[1],
            phase2_conflicts=[1, 3],
            per_anchor=[_valid_wc_row(3), _anchor_row(1, [_vote("naive", "conflict", 1.0)], "conflict", "conflict_no_safe")],
        )
        assert compute_agreement_rate([rec]) == 0.0

    def test_mixed(self):
        agree = _shadow_record(
            would_change=[], phase1_conflicts=[5],
            phase2_conflicts=[5],
            per_anchor=[_anchor_row(5, [_vote("naive", "conflict", 1.0)], "conflict", "conflict_no_safe")],
        )
        disagree = _shadow_record(
            would_change=[1], phase1_conflicts=[2],
            phase2_conflicts=[1, 2],
            per_anchor=[_valid_wc_row(1), _anchor_row(2, [_vote("naive", "conflict", 1.0)], "conflict", "conflict_no_safe")],
        )
        rate = compute_agreement_rate([agree, disagree])
        assert rate == pytest.approx(0.5)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 5. Confidence extraction
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestExtractOverrideConfidences:

    def test_basic_extraction(self):
        rec = _shadow_record(
            would_change=[10],
            phase1_conflicts=[],
            phase2_conflicts=[10],
            per_anchor=[_valid_wc_row(10, confidence=0.91)],
        )
        confs = extract_override_confidences([rec])
        assert confs == [0.91]

    def test_multiple_records(self):
        r1 = _shadow_record(
            would_change=[1], phase1_conflicts=[],
            phase2_conflicts=[1], per_anchor=[_valid_wc_row(1, 0.88)],
        )
        r2 = _shadow_record(
            would_change=[2], phase1_conflicts=[],
            phase2_conflicts=[2], per_anchor=[_valid_wc_row(2, 0.95)],
        )
        confs = extract_override_confidences([r1, r2])
        assert confs == [0.88, 0.95]

    def test_only_would_change_anchors(self):
        """Anchors NOT in would_change should not contribute confidences."""
        rec = _shadow_record(
            would_change=[10],
            phase1_conflicts=[20],
            phase2_conflicts=[10, 20],
            per_anchor=[
                _valid_wc_row(10, 0.91),
                _anchor_row(20, [
                    _vote("naive", "conflict", 1.0),
                    _vote("embedding", "conflict", 0.99),
                ], "conflict", "conflict_no_safe"),
            ],
        )
        confs = extract_override_confidences([rec])
        assert confs == [0.91]

    def test_no_shadow(self):
        assert extract_override_confidences([_no_shadow_record()]) == []

    def test_missing_anchor_row(self):
        """If would_change references an anchor with no row, skip it."""
        rec = _shadow_record(
            would_change=[99],
            phase1_conflicts=[],
            phase2_conflicts=[99],
            per_anchor=[_valid_wc_row(1)],
        )
        confs = extract_override_confidences([rec])
        assert confs == []


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 6. Confidence histogram
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestConfidenceHistogram:

    def test_single_bin(self):
        h = compute_confidence_histogram([0.86])
        assert h["[0.85, 0.87)"] == 1
        assert sum(h.values()) == 1

    def test_all_bins(self):
        h = compute_confidence_histogram([0.85, 0.87, 0.91, 0.94, 0.97])
        assert h["[0.85, 0.87)"] == 1  # 0.85
        assert h["[0.87, 0.90)"] == 1  # 0.87
        assert h["[0.90, 0.93)"] == 1  # 0.91
        assert h["[0.93, 0.96)"] == 1  # 0.94
        assert h["[0.96, 1.00]"] == 1  # 0.97

    def test_below_range_dropped(self):
        h = compute_confidence_histogram([0.80, 0.84])
        assert sum(h.values()) == 0

    def test_exact_boundaries(self):
        """0.85 is in first bin, 0.87 is in second bin."""
        h = compute_confidence_histogram([0.85, 0.87])
        assert h["[0.85, 0.87)"] == 1
        assert h["[0.87, 0.90)"] == 1

    def test_upper_edge_of_last_bin(self):
        """1.00 should fall in the [0.96, 1.00] bin."""
        h = compute_confidence_histogram([1.00])
        assert h["[0.96, 1.00]"] == 1

    def test_empty_input(self):
        h = compute_confidence_histogram([])
        assert all(v == 0 for v in h.values())

    def test_multiple_values_same_bin(self):
        h = compute_confidence_histogram([0.90, 0.91, 0.92])
        assert h["[0.90, 0.93)"] == 3

    def test_returns_all_bin_keys(self):
        h = compute_confidence_histogram([0.50])  # below range
        expected_keys = {"[0.85, 0.87)", "[0.87, 0.90)", "[0.90, 0.93)",
                        "[0.93, 0.96)", "[0.96, 1.00]"}
        assert set(h.keys()) == expected_keys


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 7. Invariant checks
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestCheckInvariants:
    """Each sub-test validates one specific invariant rule."""

    def test_clean_record_passes(self):
        rec = _shadow_record(
            would_change=[10],
            phase1_conflicts=[],
            phase2_conflicts=[10],
            per_anchor=[_valid_wc_row(10)],
        )
        assert check_invariants([rec]) == []

    def test_would_change_not_subset_of_phase2(self):
        """Rule 1: anchor in would_change but not in phase2_conflicts."""
        rec = _shadow_record(
            would_change=[99],
            phase1_conflicts=[],
            phase2_conflicts=[],
            per_anchor=[],
        )
        violations = check_invariants([rec])
        rules = {v["rule"] for v in violations}
        assert "would_change_subset_of_phase2" in rules

    def test_would_change_overlaps_phase1(self):
        """Rule 2: anchor in both would_change and phase1_conflicts."""
        rec = _shadow_record(
            would_change=[5],
            phase1_conflicts=[5],
            phase2_conflicts=[5],
            per_anchor=[_valid_wc_row(5)],
        )
        violations = check_invariants([rec])
        rules = {v["rule"] for v in violations}
        assert "would_change_disjoint_from_phase1" in rules

    def test_missing_embedding_conflict_vote(self):
        """Rule 3: would_change anchor lacks embedding conflict vote."""
        row = _anchor_row(
            anchor_id=10,
            votes=[
                _vote("naive", "safe", 1.0, "safe_lockout"),
                _vote("embedding", "abstain", 0.0, "below threshold"),
            ],
            resolved="safe",
            resolution_reason="safe_overrides_conflict",
        )
        rec = _shadow_record(
            would_change=[10],
            phase1_conflicts=[],
            phase2_conflicts=[10],
            per_anchor=[row],
        )
        violations = check_invariants([rec])
        rules = {v["rule"] for v in violations}
        assert "embedding_conflict_vote_exists" in rules

    def test_confidence_below_threshold(self):
        """Rule 4: embedding confidence < phase2_threshold."""
        row = _anchor_row(
            anchor_id=10,
            votes=[
                _vote("naive", "safe", 1.0),
                _vote("embedding", "conflict", 0.70, "cosine similarity 0.700"),
            ],
            resolved="safe",
            resolution_reason="safe_overrides_conflict",
        )
        rec = _shadow_record(
            would_change=[10],
            phase1_conflicts=[],
            phase2_conflicts=[10],
            per_anchor=[row],
            phase2_threshold=0.85,
        )
        violations = check_invariants([rec])
        rules = {v["rule"] for v in violations}
        assert "confidence_above_threshold" in rules
        assert "0.7000" in violations[0]["detail"]

    def test_wrong_resolution_reason(self):
        """Rule 5: resolution_reason is not safe_overrides_conflict."""
        row = _anchor_row(
            anchor_id=10,
            votes=[
                _vote("naive", "safe", 1.0),
                _vote("embedding", "conflict", 0.91),
            ],
            resolved="safe",
            resolution_reason="safe_preserved_embedding_below_threshold",
        )
        rec = _shadow_record(
            would_change=[10],
            phase1_conflicts=[],
            phase2_conflicts=[10],
            per_anchor=[row],
        )
        violations = check_invariants([rec])
        rules = {v["rule"] for v in violations}
        assert "resolution_reason_is_safe_overrides" in rules

    def test_missing_anchor_row(self):
        """would_change anchor has no per_anchor_votes entry at all."""
        rec = _shadow_record(
            would_change=[77],
            phase1_conflicts=[],
            phase2_conflicts=[77],
            per_anchor=[_valid_wc_row(1)],
        )
        violations = check_invariants([rec])
        rules = {v["rule"] for v in violations}
        assert "anchor_has_per_anchor_row" in rules
        # Subsequent per-anchor checks should be skipped
        for v in violations:
            if v["rule"] == "anchor_has_per_anchor_row":
                assert v["anchor_id"] == 77

    def test_multiple_violations_in_one_record(self):
        """A single record can produce multiple violations."""
        rec = _shadow_record(
            would_change=[5],
            phase1_conflicts=[5],  # Rule 2: overlap
            phase2_conflicts=[],   # Rule 1: not subset
            per_anchor=[],
        )
        violations = check_invariants([rec])
        rules = {v["rule"] for v in violations}
        assert "would_change_subset_of_phase2" in rules
        assert "would_change_disjoint_from_phase1" in rules

    def test_violations_across_records(self):
        """Violations in different records are all reported."""
        r1 = _shadow_record(
            would_change=[1], phase1_conflicts=[],
            phase2_conflicts=[], per_anchor=[],
        )
        r2 = _shadow_record(
            would_change=[], phase1_conflicts=[],
            phase2_conflicts=[], per_anchor=[],
        )
        r3 = _shadow_record(
            would_change=[2], phase1_conflicts=[],
            phase2_conflicts=[2],
            per_anchor=[
                _anchor_row(
                    2,
                    [_vote("naive", "safe", 1.0),
                     _vote("embedding", "conflict", 0.91)],
                    "safe",
                    "wrong_reason",
                ),
            ],
        )
        violations = check_invariants([r1, r2, r3])
        assert violations[0]["record_index"] == 0
        assert violations[0]["rule"] == "would_change_subset_of_phase2"
        assert violations[-1]["record_index"] == 2
        assert violations[-1]["rule"] == "resolution_reason_is_safe_overrides"

    def test_no_shadow_records_returns_empty(self):
        assert check_invariants([_no_shadow_record(), _no_shadow_record()]) == []

    def test_default_threshold_used_when_missing(self):
        """When phase2_threshold is absent, default 0.85 applies."""
        row = _anchor_row(
            anchor_id=10,
            votes=[
                _vote("naive", "safe", 1.0),
                _vote("embedding", "conflict", 0.80),
            ],
            resolved="safe",
            resolution_reason="safe_overrides_conflict",
        )
        rec = {
            "match_debug_json": {
                "phase2_shadow": {
                    "active": True,
                    "would_change": [10],
                    "phase1_conflicts": [],
                    "phase2_conflicts": [10],
                },
                # phase2_threshold deliberately omitted
                "per_anchor_votes": [row],
            },
        }
        violations = check_invariants([rec])
        rules = {v["rule"] for v in violations}
        assert "confidence_above_threshold" in rules

    def test_custom_default_threshold(self):
        """check_invariants accepts a custom default_threshold."""
        row = _anchor_row(
            anchor_id=10,
            votes=[
                _vote("naive", "safe", 1.0),
                _vote("embedding", "conflict", 0.92),
            ],
            resolved="safe",
            resolution_reason="safe_overrides_conflict",
        )
        rec = {
            "match_debug_json": {
                "phase2_shadow": {
                    "active": True,
                    "would_change": [10],
                    "phase1_conflicts": [],
                    "phase2_conflicts": [10],
                },
                "per_anchor_votes": [row],
            },
        }
        # 0.92 < 0.95 â†’ violation
        v95 = check_invariants([rec], default_threshold=0.95)
        assert any(v["rule"] == "confidence_above_threshold" for v in v95)
        # 0.92 >= 0.90 â†’ no violation
        v90 = check_invariants([rec], default_threshold=0.90)
        assert not any(v["rule"] == "confidence_above_threshold" for v in v90)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 8. Scope distribution
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestScopeDistribution:

    def test_scope_present(self):
        rec = _shadow_record(
            would_change=[10, 20],
            phase1_conflicts=[],
            phase2_conflicts=[10, 20],
            per_anchor=[
                _valid_wc_row(10, scope="safety.breakin"),
                _valid_wc_row(20, scope="safety.theft"),
            ],
        )
        dist = compute_scope_distribution([rec])
        assert dist == {"safety.breakin": 1, "safety.theft": 1}

    def test_scope_in_snapshot_scope(self):
        row = _anchor_row(
            10,
            votes=[_vote("naive", "safe", 1.0), _vote("embedding", "conflict", 0.91)],
            resolved="safe",
            resolution_reason="safe_overrides_conflict",
        )
        row["snapshot_scope"] = "payments.refunds"
        row.pop("scope", None)
        rec = _shadow_record(
            would_change=[10], phase1_conflicts=[],
            phase2_conflicts=[10], per_anchor=[row],
        )
        dist = compute_scope_distribution([rec])
        assert dist == {"payments.refunds": 1}

    def test_scope_absent_returns_empty(self):
        rec = _shadow_record(
            would_change=[10], phase1_conflicts=[],
            phase2_conflicts=[10], per_anchor=[_valid_wc_row(10)],
        )
        dist = compute_scope_distribution([rec])
        assert dist == {}

    def test_no_shadow_returns_empty(self):
        assert compute_scope_distribution([_no_shadow_record()]) == {}

    def test_only_would_change_anchors_counted(self):
        """An anchor in phase2_conflicts but NOT would_change is excluded."""
        rec = _shadow_record(
            would_change=[10],
            phase1_conflicts=[],
            phase2_conflicts=[10, 20],
            per_anchor=[
                _valid_wc_row(10, scope="safety.a"),
                _anchor_row(20, [_vote("naive", "conflict", 1.0)],
                            "conflict", "conflict_no_safe", scope="safety.b"),
            ],
        )
        dist = compute_scope_distribution([rec])
        assert dist == {"safety.a": 1}

    def test_aggregation_across_records(self):
        r1 = _shadow_record(
            would_change=[1], phase1_conflicts=[],
            phase2_conflicts=[1],
            per_anchor=[_valid_wc_row(1, scope="safety.breakin")],
        )
        r2 = _shadow_record(
            would_change=[2], phase1_conflicts=[],
            phase2_conflicts=[2],
            per_anchor=[_valid_wc_row(2, scope="safety.breakin")],
        )
        r3 = _shadow_record(
            would_change=[3], phase1_conflicts=[],
            phase2_conflicts=[3],
            per_anchor=[_valid_wc_row(3, scope="safety.theft")],
        )
        dist = compute_scope_distribution([r1, r2, r3])
        assert dist == {"safety.breakin": 2, "safety.theft": 1}

    def test_output_is_sorted(self):
        rec = _shadow_record(
            would_change=[1, 2], phase1_conflicts=[],
            phase2_conflicts=[1, 2],
            per_anchor=[
                _valid_wc_row(1, scope="z.scope"),
                _valid_wc_row(2, scope="a.scope"),
            ],
        )
        dist = compute_scope_distribution([rec])
        keys = list(dist.keys())
        assert keys == ["a.scope", "z.scope"]


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 9. summarize_phase2_shadow
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestSummarize:

    def test_returns_all_keys(self):
        s = summarize_phase2_shadow([])
        expected_keys = {
            "record_count",
            "shadow_record_count",
            "override_rate",
            "total_overridden_anchors",
            "avg_overrides_per_event",
            "agreement_rate",
            "override_confidences",
            "confidence_histogram",
            "invariant_violations",
            "invariant_violation_count",
            "invariant_violations_by_rule",
            "scope_distribution",
        }
        assert set(s.keys()) == expected_keys

    def test_comprehensive_summary(self):
        """Build a realistic multi-record scenario and check aggregation."""
        # Record 0: shadow with override
        r0 = _shadow_record(
            would_change=[10],
            phase1_conflicts=[3],
            phase2_conflicts=[3, 10],
            per_anchor=[
                _valid_wc_row(10, 0.91),
                _anchor_row(3, [_vote("naive", "conflict", 1.0)],
                            "conflict", "conflict_no_safe"),
            ],
        )
        # Record 1: shadow with no override (agree)
        r1 = _shadow_record(
            would_change=[],
            phase1_conflicts=[5],
            phase2_conflicts=[5],
            per_anchor=[
                _anchor_row(5, [_vote("naive", "conflict", 1.0)],
                            "conflict", "conflict_no_safe"),
            ],
        )
        # Record 2: no shadow at all
        r2 = _no_shadow_record()

        s = summarize_phase2_shadow([r0, r1, r2])

        assert s["record_count"] == 3
        assert s["shadow_record_count"] == 2
        assert s["override_rate"] == pytest.approx(0.5)
        assert s["agreement_rate"] == pytest.approx(0.5)
        assert s["total_overridden_anchors"] == 1
        assert s["avg_overrides_per_event"] == pytest.approx(0.5)
        assert s["override_confidences"] == [0.91]
        assert s["invariant_violation_count"] == 0
        assert s["invariant_violations_by_rule"] == {}

    def test_summary_includes_violations(self):
        bad = _shadow_record(
            would_change=[99],
            phase1_conflicts=[],
            phase2_conflicts=[],
            per_anchor=[],
        )
        s = summarize_phase2_shadow([bad])
        assert s["invariant_violation_count"] > 0
        assert len(s["invariant_violations"]) > 0
        assert isinstance(s["invariant_violations_by_rule"], dict)

    def test_summary_histogram(self):
        rec = _shadow_record(
            would_change=[1, 2],
            phase1_conflicts=[],
            phase2_conflicts=[1, 2],
            per_anchor=[
                _valid_wc_row(1, 0.88),
                _valid_wc_row(2, 0.95),
            ],
        )
        s = summarize_phase2_shadow([rec])
        assert s["confidence_histogram"]["[0.87, 0.90)"] == 1
        assert s["confidence_histogram"]["[0.93, 0.96)"] == 1


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 10. JSON-encoded match_debug_json
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestJsonEncodedMatchDebug:

    def test_json_string_input(self):
        """match_debug_json can be a JSON string, not just a dict."""
        inner = {
            "matcher_mode": "signals_v1",
            "per_anchor_votes": [_valid_wc_row(10, 0.91)],
            "phase2_active": True,
            "phase2_threshold": 0.85,
            "phase2_shadow": {
                "active": True,
                "would_change": [10],
                "phase1_conflicts": [],
                "phase2_conflicts": [10],
            },
        }
        rec = {"match_debug_json": json.dumps(inner)}

        assert compute_override_rate([rec]) == 1.0
        assert extract_override_confidences([rec]) == [0.91]
        assert check_invariants([rec]) == []

    def test_invalid_json_graceful(self):
        """Malformed JSON string should be treated as empty match_debug."""
        rec = {"match_debug_json": "{not valid json"}
        assert compute_override_rate([rec]) == 0.0
        assert check_invariants([rec]) == []

    def test_non_dict_non_string_match_debug(self):
        """match_debug_json as an int or None should not crash."""
        assert compute_override_rate([{"match_debug_json": 42}]) == 0.0
        assert compute_override_rate([{"match_debug_json": None}]) == 0.0


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 11. Edge cases
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestEdgeCases:

    def test_empty_would_change_in_shadow(self):
        rec = _shadow_record(
            would_change=[],
            phase1_conflicts=[],
            phase2_conflicts=[],
            per_anchor=[],
        )
        assert compute_override_rate([rec]) == 0.0
        assert extract_override_confidences([rec]) == []
        assert check_invariants([rec]) == []

    def test_missing_optional_shadow_fields(self):
        """Shadow dict missing would_change / phase1_conflicts etc."""
        rec = {
            "match_debug_json": {
                "phase2_shadow": {"active": True},
                "per_anchor_votes": [],
            },
        }
        assert compute_override_rate([rec]) == 0.0
        assert compute_agreement_rate([rec]) == 1.0  # empty == empty
        assert check_invariants([rec]) == []

    def test_record_without_match_debug_key(self):
        assert compute_override_rate([{}]) == 0.0
        assert check_invariants([{}]) == []

    def test_confidence_histogram_out_of_range(self):
        h = compute_confidence_histogram([0.50, 1.01, -0.1, 2.0])
        assert sum(h.values()) == 0

    def test_violation_detail_contains_anchor_info(self):
        """Each violation should carry record_index and anchor_id."""
        rec = _shadow_record(
            would_change=[42],
            phase1_conflicts=[],
            phase2_conflicts=[],
            per_anchor=[],
        )
        violations = check_invariants([rec])
        assert len(violations) >= 1
        for v in violations:
            assert "record_index" in v
            assert "anchor_id" in v
            assert "rule" in v
            assert "detail" in v