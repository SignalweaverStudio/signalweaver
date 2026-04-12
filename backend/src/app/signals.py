"""
signals.py -- Phase 1 signal competition layer

- SignalVote: immutable vote primitive
- naive_votes: wraps naive_conflicts()
- embedding_votes: wraps find_conflicts_embedding() (fail-safe)
- resolve_votes: simple resolver (safe > conflict > abstain)
- build_match_debug: deterministic debug output

No DB usage. No dependency on gate.py (except injected functions).
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


# ───────────────────────────────────────────────────────────────
# SignalVote
# ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SignalVote:
    anchor_id: int
    verdict: str          # "conflict" | "safe" | "abstain"
    confidence: float     # 0.0–1.0
    matcher_name: str
    explanation: str


# ───────────────────────────────────────────────────────────────
# Constants (mirrors gate.py logic)
# ───────────────────────────────────────────────────────────────

SAFE_MARKERS = {
    "legal", "lawful", "locksmith", "roadside",
    "assistance", "manufacturer", "proof", "ownership",
    "insurance", "police", "tow",
}

AVOID_MARKERS = {
    "avoid", "do not", "dont", "no forced entry",
}

HIGH_RISK_PHRASES = {
    "break into", "break in", "bypass", "lockpick",
    "pick lock", "hotwire", "steal", "theft",
}

SAFE_ANCHOR_PATTERNS = {
    "break into",
    "bypass",
    "lockpick",
}


def _default_norm(s: str) -> str:
    return " ".join(s.strip().lower().split())


# ───────────────────────────────────────────────────────────────
# Naive matcher wrapper
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
            votes.append(SignalVote(
                anchor_id=a.id,
                verdict="conflict",
                confidence=1.0,
                matcher_name="naive",
                explanation="matched by naive rules",
            ))

        elif safe_lockout and not has_high_risk and any(p in stmt for p in SAFE_ANCHOR_PATTERNS):
            votes.append(SignalVote(
                anchor_id=a.id,
                verdict="safe",
                confidence=1.0,
                matcher_name="naive",
                explanation="safe_lockout detected",
            ))

        else:
            votes.append(SignalVote(
                anchor_id=a.id,
                verdict="abstain",
                confidence=0.0,
                matcher_name="naive",
                explanation="no naive match",
            ))

    return votes


# ───────────────────────────────────────────────────────────────
# Embedding matcher wrapper
# ───────────────────────────────────────────────────────────────

def embedding_votes(
    request_text: str,
    anchors: List[Any],
    *,
    threshold: float = 0.50,
) -> List[SignalVote]:

    conflict_ids = set()
    scores: Dict[int, float] = {}

    try:
        from app.embedding_matcher import find_conflicts_embedding

        scored = find_conflicts_embedding(
            request_text,
            anchors,
            threshold=threshold,
        )

        for a, score in scored:
            conflict_ids.add(a.id)
            scores[a.id] = float(score)

    except Exception:
        # fail-safe: all abstain
        pass

    votes: List[SignalVote] = []

    for a in anchors:
        if a.id in conflict_ids:
            votes.append(SignalVote(
                anchor_id=a.id,
                verdict="conflict",
                confidence=scores[a.id],
                matcher_name="embedding",
                explanation=f"cosine similarity {scores[a.id]:.3f}",
            ))
        else:
            votes.append(SignalVote(
                anchor_id=a.id,
                verdict="abstain",
                confidence=0.0,
                matcher_name="embedding",
                explanation="below threshold or no match",
            ))

    return votes


# ───────────────────────────────────────────────────────────────
# Resolver
# ───────────────────────────────────────────────────────────────

def resolve_votes(
    votes: List[SignalVote],
) -> Dict[int, str]:

    by_anchor: Dict[int, List[SignalVote]] = {}

    for v in votes:
        by_anchor.setdefault(v.anchor_id, []).append(v)

    conflicts: Dict[int, str] = {}

    for aid, vs in by_anchor.items():
        verdicts = {v.verdict for v in vs}

        if "safe" in verdicts:
            continue

        if "conflict" in verdicts:
            conflicts[aid] = "conflict"

    return conflicts


# ───────────────────────────────────────────────────────────────
# Debug builder (deterministic)
# ───────────────────────────────────────────────────────────────

def build_match_debug(
    votes: List[SignalVote],
    resolved: Dict[int, str],
    anchor_count: int,
) -> Dict[str, Any]:

    anchor_ids = sorted({v.anchor_id for v in votes})

    per_anchor = []

    for aid in anchor_ids:
        vs = sorted(
            [v for v in votes if v.anchor_id == aid],
            key=lambda x: (x.matcher_name, x.verdict),
        )

        per_anchor.append({
            "anchor_id": aid,
            "votes": [
                {
                    "matcher": v.matcher_name,
                    "verdict": v.verdict,
                    "confidence": v.confidence,
                    "explanation": v.explanation,
                }
                for v in vs
            ],
            "resolved": resolved.get(aid, "safe"),
        })

    return {
        "matcher_mode": "signals_v1",
        "evaluated_anchor_count": anchor_count,
        "conflicted_ids": sorted(resolved.keys()),
        "per_anchor_votes": per_anchor,
    }