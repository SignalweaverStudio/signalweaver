from __future__ import annotations
import os
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────────
# SignalVote & Hardened Constants (Patch 1 & 2)
# ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SignalVote:
    anchor_id: int
    verdict: str        # "conflict" | "safe" | "abstain"
    confidence: float   # 0.0–1.0
    matcher_name: str
    explanation: str

SAFE_MARKERS: frozenset[str] = frozenset({
    "legal", "lawful", "licensed", "locksmith", "roadside",
    "assistance", "manufacturer", "proof", "ownership",
    "insurance", "police", "tow",
})

AVOID_MARKERS: frozenset[str] = frozenset({
    "avoid", "please avoid", "do not", "dont",
    "without details", "no forced entry",
})

HIGH_RISK_PHRASES: frozenset[str] = frozenset({
    "break into", "break in", "bypass", "lockpick",
    "pick lock", "hotwire", "slim jim", "jimmy",
    "forced entry", "steal", "theft",
})

SAFE_ANCHOR_PATTERNS: frozenset[str] = frozenset({
    "break into", "bypass", "lockpick",
    "bypassing locks", "breaking into cars",
})

PHASE2_OVERRIDE_THRESHOLD: float = float(
    os.getenv("SW_PHASE2_OVERRIDE_THRESHOLD", "0.85")
)

def _default_norm(s: str) -> str:
    return " ".join(s.strip().lower().split())

# ───────────────────────────────────────────────────────────────
# Matcher Wrappers
# ───────────────────────────────────────────────────────────────

def naive_votes(
    request_text: str,
    anchors: List[Any],
    *,
    _naive_fn: Optional[Callable] = None,
    _norm_fn: Optional[Callable] = None,
) -> List[SignalVote]:
    if _naive_fn is None:
        from app.api.gate import naive_conflicts as _naive_fn

    _norm = _norm_fn or _default_norm
    conflicts = _naive_fn(request_text, anchors)
    conflict_ids = {a.id for a in conflicts}

    req = _norm(request_text)
    has_safe = any(w in req for w in SAFE_MARKERS)
    has_avoid = any(w in req for w in AVOID_MARKERS)
    has_high_risk = any(p in req for p in HIGH_RISK_PHRASES)
    safe_lockout = has_safe and has_avoid

    votes: List[SignalVote] = []
    for a in anchors:
        stmt = _norm(a.statement)
        if a.id in conflict_ids:
            votes.append(SignalVote(a.id, "conflict", 1.0, "naive", "matched by naive rules"))
        elif safe_lockout and not has_high_risk and any(p in stmt for p in SAFE_ANCHOR_PATTERNS):
            votes.append(SignalVote(a.id, "safe", 1.0, "naive", "safe_lockout detected"))
        else:
            votes.append(SignalVote(a.id, "abstain", 0.0, "naive", "no naive match"))
    return votes

def embedding_votes(
    request_text: str,
    anchors: List[Any],
    *,
    threshold: float = 0.50,
) -> List[SignalVote]:
    # Kill Switch & Limit Guards (Patch 3 & 4)
    if os.getenv("SW_EMBEDDING_ENABLED", "true").lower() not in ("true", "1", "yes"):
        return [SignalVote(a.id, "abstain", 0.0, "embedding", "disabled by SW_EMBEDDING_ENABLED") for a in anchors]

    max_anchors = int(os.getenv("SW_EMBEDDING_MAX_ANCHORS", "50"))
    if len(anchors) > max_anchors:
        return [SignalVote(a.id, "abstain", 0.0, "embedding", f"anchor limit {max_anchors} exceeded") for a in anchors]

    conflict_ids = set()
    scores: Dict[int, float] = {}
    embedding_failed = False

    try:
        from app.embedding_matcher import find_conflicts_embedding
        scored = find_conflicts_embedding(request_text, anchors, threshold=threshold)
        for a, score in scored:
            conflict_ids.add(a.id)
            scores[a.id] = float(score)
    except Exception as e:
        logger.error(f"Embedding failure: {e}")
        embedding_failed = True

    votes: List[SignalVote] = []
    for a in anchors:
        if a.id in conflict_ids:
            votes.append(SignalVote(a.id, "conflict", scores[a.id], "embedding", f"cosine similarity {scores[a.id]:.3f}"))
        else:
            # Failure Visibility (Patch 5)
            explanation = "embedding_failure_degraded" if embedding_failed else "below threshold or no match"
            votes.append(SignalVote(a.id, "abstain", 0.0, "embedding", explanation))
    return votes

# ───────────────────────────────────────────────────────────────
# Phase 2 Resolver & Debug
# ───────────────────────────────────────────────────────────────

def resolve_votes(
    votes: List[SignalVote],
    *,
    phase2_enabled: bool = False,
) -> Tuple[Dict[int, str], Dict[int, str]]:
    by_anchor: Dict[int, List[SignalVote]] = {}
    for v in votes:
        by_anchor.setdefault(v.anchor_id, []).append(v)

    conflicts: Dict[int, str] = {}
    reasons: Dict[int, str] = {}

    for aid, vs in by_anchor.items():
        verdicts = {v.verdict for v in vs}

        if "safe" in verdicts and "conflict" in verdicts:
            if not phase2_enabled:
                reasons[aid] = "safe_overrides_conflict"
                continue

            max_emb_conf = max(
                (v.confidence for v in vs if v.verdict == "conflict" and v.matcher_name == "embedding"),
                default=0.0,
            )

            if max_emb_conf >= PHASE2_OVERRIDE_THRESHOLD:
                conflicts[aid] = "conflict"
                reasons[aid] = "safe_overridden_by_high_confidence_embedding"
            else:
                reasons[aid] = "safe_preserved_embedding_below_threshold"

        elif "safe" in verdicts:
            reasons[aid] = "safe_no_conflict"
        elif "conflict" in verdicts:
            conflicts[aid] = "conflict"
            reasons[aid] = "conflict_no_safe"

    return conflicts, reasons

def build_match_debug(
    votes: List[SignalVote],
    resolved: Dict[int, str],
    anchor_count: int,
    resolution_reasons: Optional[Dict[int, str]] = None,
    phase2_active: bool = False,
    phase2_threshold: Optional[float] = None,
) -> Dict[str, Any]:
    anchor_ids = sorted({v.anchor_id for v in votes})
    reasons = resolution_reasons or {}
    per_anchor = []

    for aid in anchor_ids:
        vs = sorted([v for v in votes if v.anchor_id == aid], key=lambda x: (x.matcher_name, x.verdict))
        row = {
            "anchor_id": aid,
            "votes": [{"matcher": v.matcher_name, "verdict": v.verdict, "confidence": v.confidence, "explanation": v.explanation} for v in vs],
            "resolved": resolved.get(aid, "safe"),
        }
        if reasons:
            row["resolution_reason"] = reasons.get(aid, "abstain")
        per_anchor.append(row)

    result = {
        "matcher_mode": "signals_v1",
        "evaluated_anchor_count": anchor_count,
        "conflicted_ids": sorted(resolved.keys()),
        "per_anchor_votes": per_anchor,
    }
    if phase2_active:
        result["phase2_active"] = True
        result["phase2_threshold"] = phase2_threshold or PHASE2_OVERRIDE_THRESHOLD
    return result