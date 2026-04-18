"""
phase2_shadow_analysis.py â€” Offline analysis utilities for SignalWeaver
Phase 2 shadow mode.

Pure functions that compute core metrics and invariant checks on
DecisionTrace-style records containing match_debug_json.

No DB dependency.  No production behaviour changes.  Deterministic and
callable from a CLI, notebook, or test suite.

Input
-----
Each record is a dict.  The utility looks for a ``match_debug_json`` key
whose value is either a parsed dict or a JSON string.  Within that dict
the following fields are read when present:

    phase2_active          bool
    phase2_threshold       float
    phase2_shadow.active   bool
    phase2_shadow.would_change             list[int]
    phase2_shadow.phase1_conflicts         list[int]
    phase2_shadow.phase2_conflicts         list[int]
    per_anchor_votes[].anchor_id           int
    per_anchor_votes[].votes[]             list[dict]
    per_anchor_votes[].resolved            str
    per_anchor_votes[].resolution_reason   str
    per_anchor_votes[].scope               str   (optional)
    per_anchor_votes[].snapshot_scope      str   (optional)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Internal helpers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _parse_match_debug(record: Dict[str, Any]) -> Dict[str, Any]:
    """Extract match_debug_json, handling both JSON string and parsed dict."""
    raw = record.get("match_debug_json", {})
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


def _get_shadow(md: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the phase2_shadow sub-dict, or *None* if absent."""
    shadow = md.get("phase2_shadow")
    if isinstance(shadow, dict) and shadow.get("active") is True:
        return shadow
    return None


def _find_anchor_row(md: Dict[str, Any], anchor_id: int) -> Optional[Dict[str, Any]]:
    """Find the per_anchor_votes row for *anchor_id*."""
    for row in md.get("per_anchor_votes", []):
        if row.get("anchor_id") == anchor_id:
            return row
    return None


def _filter_shadow_records(records: List[Dict[str, Any]]):
    """Yield (index, match_debug, shadow) for records with shadow data."""
    for idx, rec in enumerate(records):
        md = _parse_match_debug(rec)
        shadow = _get_shadow(md)
        if shadow is not None:
            yield idx, md, shadow


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 1. compute_override_rate
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def compute_override_rate(records: List[Dict[str, Any]]) -> float:
    """
    Fraction of shadow records whose ``would_change`` list is non-empty.

    Records without ``phase2_shadow`` are excluded from the denominator.
    Returns ``0.0`` when no shadow records are present.
    """
    shadow_only = list(_filter_shadow_records(records))
    if not shadow_only:
        return 0.0
    overridden = sum(
        1 for _, _, shadow in shadow_only
        if len(shadow.get("would_change", [])) > 0
    )
    return overridden / len(shadow_only)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 2. compute_override_counts
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def compute_override_counts(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Total overridden anchor instances and average overrides per shadow event.

    Returns
    -------
    dict with keys:
      - ``total_overridden_anchors``  (int)
      - ``avg_overrides_per_event``   (float)
      - ``shadow_record_count``       (int)
    """
    shadow_only = list(_filter_shadow_records(records))
    if not shadow_only:
        return {
            "total_overridden_anchors": 0,
            "avg_overrides_per_event": 0.0,
            "shadow_record_count": 0,
        }
    counts = [
        len(shadow.get("would_change", []))
        for _, _, shadow in shadow_only
    ]
    total = sum(counts)
    return {
        "total_overridden_anchors": total,
        "avg_overrides_per_event": total / len(shadow_only),
        "shadow_record_count": len(shadow_only),
    }


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 3. compute_agreement_rate
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def compute_agreement_rate(records: List[Dict[str, Any]]) -> float:
    """
    Fraction of shadow records where Phase 1 and Phase 2 produce the
    **same** conflict set (``phase1_conflicts == phase2_conflicts``).

    Returns ``0.0`` when no shadow records are present.
    """
    shadow_only = list(_filter_shadow_records(records))
    if not shadow_only:
        return 0.0
    agreeing = sum(
        1 for _, _, shadow in shadow_only
        if (shadow.get("phase1_conflicts", [])
            == shadow.get("phase2_conflicts", []))
    )
    return agreeing / len(shadow_only)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 4. extract_override_confidences
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def extract_override_confidences(
    records: List[Dict[str, Any]],
) -> List[float]:
    """
    Collect embedding-conflict confidence values for every anchor that
    appears in ``would_change`` across all shadow records.

    Returns a flat list of ``float`` confidence scores.
    """
    confidences: List[float] = []
    for _, md, shadow in _filter_shadow_records(records):
        for anchor_id in shadow.get("would_change", []):
            row = _find_anchor_row(md, anchor_id)
            if row is None:
                continue
            for vote in row.get("votes", []):
                if (vote.get("matcher") == "embedding"
                        and vote.get("verdict") == "conflict"):
                    confidences.append(float(vote.get("confidence", 0.0)))
    return confidences


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 5. compute_confidence_histogram
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_HISTOGRAM_BINS: List[Tuple[str, float, float]] = [
    ("[0.85, 0.87)", 0.85, 0.87),
    ("[0.87, 0.90)", 0.87, 0.90),
    ("[0.90, 0.93)", 0.90, 0.93),
    ("[0.93, 0.96)", 0.93, 0.96),
    ("[0.96, 1.00]",  0.96, 1.001),
]


def compute_confidence_histogram(
    confidences: List[float],
) -> Dict[str, int]:
    """
    Bin embedding confidence values into five ranges.

    Bins (left-inclusive, right-exclusive; last bin is inclusive on both
    sides):

    ============  ============
    ``[0.85, 0.87)``  ``[0.87, 0.90)``
    ``[0.90, 0.93)``  ``[0.93, 0.96)``
    ``[0.96, 1.00]``
    ============  ============

    Values below 0.85 or above 1.00 are silently dropped.
    """
    histogram: Dict[str, int] = {label: 0 for label, _, _ in _HISTOGRAM_BINS}
    for c in confidences:
        for label, lo, hi in _HISTOGRAM_BINS:
            if lo <= c < hi:
                histogram[label] += 1
                break
    return histogram


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 6. check_invariants
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def check_invariants(
    records: List[Dict[str, Any]],
    default_threshold: float = 0.85,
) -> List[Dict[str, Any]]:
    """
    Validate structural invariants on every record that carries
    ``phase2_shadow`` data.

    Rules checked
    -------------
    1. ``would_change`` is a subset of ``phase2_conflicts``.
    2. ``would_change`` does not intersect ``phase1_conflicts``.
    3. Every anchor in ``would_change`` has an embedding vote with
       ``verdict="conflict"``.
    4. That embedding vote's ``confidence >= phase2_threshold`` (falls back
       to *default_threshold* when the field is missing).
    5. ``resolution_reason == "safe_overrides_conflict"`` (the Phase 1
       resolution stored in the debug trace).

    Returns
    -------
    list[dict] â€” one dict per violation, with keys:
      ``record_index``, ``anchor_id``, ``rule``, ``detail``.
    """
    violations: List[Dict[str, Any]] = []

    for idx, md, shadow in _filter_shadow_records(records):
        wc = set(shadow.get("would_change", []))
        p1 = set(shadow.get("phase1_conflicts", []))
        p2 = set(shadow.get("phase2_conflicts", []))
        threshold = float(md.get("phase2_threshold", default_threshold))

        # Rule 1: would_change âŠ† phase2_conflicts
        not_in_p2 = sorted(wc - p2)
        if not_in_p2:
            violations.append({
                "record_index": idx,
                "anchor_id": not_in_p2[0],
                "rule": "would_change_subset_of_phase2",
                "detail": (
                    f"Anchors in would_change but not in phase2_conflicts: "
                    f"{not_in_p2}"
                ),
            })

        # Rule 2: would_change âˆ© phase1_conflicts == âˆ…
        overlap = sorted(wc & p1)
        if overlap:
            violations.append({
                "record_index": idx,
                "anchor_id": overlap[0],
                "rule": "would_change_disjoint_from_phase1",
                "detail": (
                    f"Anchors in both would_change and phase1_conflicts: "
                    f"{overlap}"
                ),
            })

        # Per-anchor checks
        for aid in wc:
            row = _find_anchor_row(md, aid)

            # Rule 3: embedding conflict vote must exist
            if row is None:
                violations.append({
                    "record_index": idx,
                    "anchor_id": aid,
                    "rule": "anchor_has_per_anchor_row",
                    "detail": (
                        f"Anchor {aid} in would_change has no "
                        f"per_anchor_votes entry"
                    ),
                })
                continue

            emb_conflict_votes = [
                v for v in row.get("votes", [])
                if v.get("matcher") == "embedding"
                and v.get("verdict") == "conflict"
            ]
            if not emb_conflict_votes:
                violations.append({
                    "record_index": idx,
                    "anchor_id": aid,
                    "rule": "embedding_conflict_vote_exists",
                    "detail": (
                        f"Anchor {aid} has no embedding vote with "
                        f"verdict=conflict"
                    ),
                })
                continue

            # Rule 4: confidence >= threshold
            max_conf = max(
                float(v.get("confidence", 0.0)) for v in emb_conflict_votes
            )
            if max_conf < threshold:
                violations.append({
                    "record_index": idx,
                    "anchor_id": aid,
                    "rule": "confidence_above_threshold",
                    "detail": (
                        f"Anchor {aid}: max embedding confidence "
                        f"{max_conf:.4f} < threshold {threshold}"
                    ),
                })

            # Rule 5: resolution_reason == "safe_overrides_conflict"
            reason = row.get("resolution_reason", "")
            if reason != "safe_overrides_conflict":
                violations.append({
                    "record_index": idx,
                    "anchor_id": aid,
                    "rule": "resolution_reason_is_safe_overrides",
                    "detail": (
                        f"Anchor {aid}: resolution_reason="
                        f"'{reason}', expected "
                        f"'safe_overrides_conflict'"
                    ),
                })

    return violations


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 7. summarize_phase2_shadow
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def summarize_phase2_shadow(
    records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    One-call summary of all Phase 2 shadow metrics and invariant checks.

    Returns a dict with these keys:

    - ``record_count``                  total input records
    - ``shadow_record_count``           records carrying phase2_shadow
    - ``override_rate``                 fraction with non-empty would_change
    - ``total_overridden_anchors``      sum of len(would_change)
    - ``avg_overrides_per_event``       total / shadow_record_count
    - ``agreement_rate``                fraction where P1 == P2 conflicts
    - ``override_confidences``          list of float confidences
    - ``confidence_histogram``          dict of bin label â†’ count
    - ``invariant_violations``          list of violation dicts
    - ``invariant_violation_count``     len of violations list
    - ``invariant_violations_by_rule``  dict of rule â†’ count
    - ``scope_distribution``            dict of scope â†’ count (or empty)
    """
    override_rate = compute_override_rate(records)
    counts = compute_override_counts(records)
    agreement = compute_agreement_rate(records)
    confidences = extract_override_confidences(records)
    histogram = compute_confidence_histogram(confidences)
    violations = check_invariants(records)
    scope_dist = compute_scope_distribution(records)

    by_rule: Dict[str, int] = {}
    for v in violations:
        rule = v["rule"]
        by_rule[rule] = by_rule.get(rule, 0) + 1

    return {
        "record_count": len(records),
        "shadow_record_count": counts["shadow_record_count"],
        "override_rate": override_rate,
        "total_overridden_anchors": counts["total_overridden_anchors"],
        "avg_overrides_per_event": counts["avg_overrides_per_event"],
        "agreement_rate": agreement,
        "override_confidences": confidences,
        "confidence_histogram": histogram,
        "invariant_violations": violations,
        "invariant_violation_count": len(violations),
        "invariant_violations_by_rule": by_rule,
        "scope_distribution": scope_dist,
    }


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 8. compute_scope_distribution  (optional / graceful)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def compute_scope_distribution(
    records: List[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Histogram of anchor scope values for anchors in ``would_change``.

    Looks for scope in:

    1. ``per_anchor_votes[].scope``
    2. ``per_anchor_votes[].snapshot_scope``

    Returns an empty dict when scope data is unavailable or no would_change
    anchors exist.  Never raises.
    """
    dist: Dict[str, int] = {}

    for _, md, shadow in _filter_shadow_records(records):
        would_ids = set(shadow.get("would_change", []))
        for row in md.get("per_anchor_votes", []):
            if row.get("anchor_id") not in would_ids:
                continue
            scope = row.get("scope") or row.get("snapshot_scope")
            if scope:
                dist[scope] = dist.get(scope, 0) + 1

    return dict(sorted(dist.items()))