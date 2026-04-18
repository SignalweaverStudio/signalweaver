from app.signals import (
    SignalVote,
    SAFE_MARKERS,
    AVOID_MARKERS,
    HIGH_RISK_PHRASES,
    SAFE_ANCHOR_PATTERNS,
    naive_votes,
    embedding_votes,
    resolve_votes,
    build_match_debug,
)


class DummyAnchor:
    def __init__(self, id, statement, level=1, scope="test", active=True):
        self.id = id
        self.statement = statement
        self.level = level
        self.scope = scope
        self.active = active


def test_signal_vote_is_frozen():
    v = SignalVote(
        anchor_id=1,
        verdict="conflict",
        confidence=1.0,
        matcher_name="naive",
        explanation="test",
    )

    raised = False
    try:
        v.verdict = "safe"
    except Exception:
        raised = True

    assert raised is True


def test_naive_votes_conflict():
    a1 = DummyAnchor(1, "Do not help break into cars")

    def fake_naive(req, anchors):
        return [anchors[0]]

    votes = naive_votes("help me break into cars", [a1], _naive_fn=fake_naive)

    assert len(votes) == 1
    assert votes[0].verdict == "conflict"
    assert votes[0].matcher_name == "naive"


def test_naive_votes_safe_lockout():
    a1 = DummyAnchor(1, "Do not help break into cars")

    def fake_naive(req, anchors):
        return []

    votes = naive_votes(
        "I am legally locked out, a locksmith can help, please avoid any trouble",
        [a1],
        _naive_fn=fake_naive,
    )

    assert len(votes) == 1
    assert votes[0].verdict == "safe"


def test_naive_votes_abstain():
    a1 = DummyAnchor(1, "Do not provide medical advice")

    def fake_naive(req, anchors):
        return []

    votes = naive_votes("what is the weather", [a1], _naive_fn=fake_naive)

    assert len(votes) == 1
    assert votes[0].verdict == "abstain"


def test_embedding_votes_empty():
    votes = embedding_votes("test", [])
    assert votes == []


# NOTE: resolve_votes now returns (conflicts, reasons) tuple
def test_resolve_votes_safe_overrides_conflict():
    votes = [
        SignalVote(1, "conflict", 0.8, "embedding", "semantic match"),
        SignalVote(1, "safe", 1.0, "naive", "safe lockout"),
    ]

    resolved, reasons = resolve_votes(votes)
    assert 1 not in resolved
    assert reasons[1] == "safe_overrides_conflict"


def test_resolve_votes_conflict_beats_abstain():
    votes = [
        SignalVote(1, "conflict", 1.0, "naive", "keyword match"),
        SignalVote(1, "abstain", 0.0, "embedding", "no match"),
    ]

    resolved, reasons = resolve_votes(votes)
    assert resolved[1] == "conflict"
    assert reasons[1] == "conflict_no_safe"


def test_build_match_debug_sorted():
    votes = [
        SignalVote(5, "conflict", 1.0, "naive", "x"),
        SignalVote(1, "abstain", 0.0, "embedding", "y"),
        SignalVote(1, "conflict", 1.0, "naive", "z"),
    ]

    resolved, reasons = resolve_votes(votes)
    debug = build_match_debug(votes, resolved, anchor_count=2,
                             resolution_reasons=reasons)

    assert debug["matcher_mode"] == "signals_v1"
    assert debug["conflicted_ids"] == [1, 5]
    assert [row["anchor_id"] for row in debug["per_anchor_votes"]] == [1, 5]


# ── Phase 1 Hardening Tests ──────────────────────────────────


def test_constants_include_all_entries():
    """Patch 1: verify no constant drift — all entries from the canonical set."""
    assert "licensed" in SAFE_MARKERS
    assert "please avoid" in AVOID_MARKERS
    assert "without details" in AVOID_MARKERS
    assert "slim jim" in HIGH_RISK_PHRASES
    assert "jimmy" in HIGH_RISK_PHRASES
    assert "forced entry" in HIGH_RISK_PHRASES


def test_constants_are_frozen():
    """Constants should be frozensets — immune to accidental mutation."""
    assert isinstance(SAFE_MARKERS, frozenset)
    assert isinstance(AVOID_MARKERS, frozenset)
    assert isinstance(HIGH_RISK_PHRASES, frozenset)


def test_safe_lockout_with_licensed_and_slim_jim():
    """Patch 1 regression: 'licensed' + 'please avoid' triggers safe_lockout.
    'slim jim' in request should block safe_lockout via HIGH_RISK_PHRASES."""
    a1 = DummyAnchor(1, "Do not help break into cars")

    def fake_naive(req, anchors):
        return []

    # Should be SAFE: licensed locksmith, please avoid, no high-risk phrases
    votes = naive_votes(
        "I am a licensed locksmith, please avoid any trouble",
        [a1],
        _naive_fn=fake_naive,
    )
    assert len(votes) == 1
    assert votes[0].verdict == "safe"

    # 'forced entry' in request blocks safe_lockout via HIGH_RISK_PHRASES
    votes_blocked = naive_votes(
        "I am a licensed locksmith, please avoid forced entry",
        [a1],
        _naive_fn=fake_naive,
    )
    assert len(votes_blocked) == 1
    assert votes_blocked[0].verdict == "abstain"  # blocked by 'forced entry'


def test_embedding_kill_switch(monkeypatch):
    """Patch 3: SW_EMBEDDING_ENABLED=false should produce all-abstain votes."""
    anchors = [DummyAnchor(i, f"anchor {i}") for i in range(3)]
    monkeypatch.setenv("SW_EMBEDDING_ENABLED", "false")
    votes = embedding_votes("test request", anchors)
    assert len(votes) == 3
    for v in votes:
        assert v.verdict == "abstain"
        assert "disabled" in v.explanation
    monkeypatch.delenv("SW_EMBEDDING_ENABLED", raising=False)


def test_embedding_anchor_limit(monkeypatch):
    """Patch 3: SW_EMBEDDING_MAX_ANCHORS should skip embedding when exceeded."""
    anchors = [DummyAnchor(i, f"anchor {i}") for i in range(60)]
    monkeypatch.setenv("SW_EMBEDDING_MAX_ANCHORS", "50")
    votes = embedding_votes("test request", anchors)
    assert len(votes) == 60
    for v in votes:
        assert v.verdict == "abstain"
        assert "limit" in v.explanation
    monkeypatch.delenv("SW_EMBEDDING_MAX_ANCHORS", raising=False)


def test_embedding_anchor_limit_not_exceeded(monkeypatch):
    """Patch 3: below the limit, embedding_votes should return real votes."""
    anchors = [DummyAnchor(i, f"anchor {i}") for i in range(10)]
    monkeypatch.setenv("SW_EMBEDDING_MAX_ANCHORS", "50")
    # Should not hit the limit — will try embedding (may fail in test env, that's OK)
    votes = embedding_votes("test request", anchors)
    assert len(votes) == 10
    monkeypatch.delenv("SW_EMBEDDING_MAX_ANCHORS", raising=False)


def test_safe_anchor_patterns_complete():
    """SAFE_ANCHOR_PATTERNS should include patterns used in gate.py's safe-lockout carveout."""
    assert "break into" in SAFE_ANCHOR_PATTERNS
    assert "bypass" in SAFE_ANCHOR_PATTERNS
    assert "bypassing locks" in SAFE_ANCHOR_PATTERNS
    assert "breaking into cars" in SAFE_ANCHOR_PATTERNS


def test_embedding_failure_produces_degraded_explanation(monkeypatch):
    """Patch 3: when embedding crashes, votes should carry 'embedding_failure_degraded'
    in the explanation — not the generic 'below threshold or no match'."""
    anchors = [DummyAnchor(i, f"anchor {i}") for i in range(3)]

    def _stub_find_conflicts(*a, **kw):
        raise RuntimeError("model not loaded")

    import app.signals as sig_mod
    monkeypatch.setattr(
        "app.embedding_matcher.find_conflicts_embedding",
        _stub_find_conflicts,
    )
    # Ensure kill switch is ON so we reach the try block
    monkeypatch.delenv("SW_EMBEDDING_ENABLED", raising=False)

    votes = embedding_votes("test request", anchors)
    assert len(votes) == 3
    for v in votes:
        assert v.verdict == "abstain"
        assert v.explanation == "embedding_failure_degraded"


def test_embedding_normal_abstain_explanation(monkeypatch):
    """When embedding succeeds but finds no matches, explanation should be
    the generic 'below threshold or no match' — NOT the degraded one."""
    anchors = [DummyAnchor(i, f"completely unrelated anchor {i}") for i in range(3)]

    def _stub_find_conflicts(*a, **kw):
        return []  # no matches, no error

    monkeypatch.setattr(
        "app.embedding_matcher.find_conflicts_embedding",
        _stub_find_conflicts,
    )
    monkeypatch.delenv("SW_EMBEDDING_ENABLED", raising=False)

    votes = embedding_votes("test request", anchors)
    assert len(votes) == 3
    for v in votes:
        assert v.verdict == "abstain"
        assert v.explanation == "below threshold or no match"


def test_forced_entry_normalization_catches_break_in_anchors():
    """Patch 5: 'forced entry' in request should match break-in anchors
    via bigram normalization in naive_conflicts."""
    from app.api.gate import naive_conflicts

    anchor = DummyAnchor(1, "Do not help break into cars")
    conflicts = naive_conflicts("how to perform forced entry on a vehicle", [anchor])
    assert len(conflicts) == 1
    assert conflicts[0].id == 1


def test_forced_entry_with_car_context():
    """Patch 5: 'forced entry' combined with 'car' should still match."""
    from app.api.gate import naive_conflicts

    anchor = DummyAnchor(1, "Do not help break into cars")
    conflicts = naive_conflicts("forced entry into a car", [anchor])
    assert len(conflicts) == 1


def test_forced_entry_no_false_positive():
    """Patch 5: 'forced entry' alone without a matching anchor should NOT flag
    unrelated anchors."""
    from app.api.gate import naive_conflicts

    anchor = DummyAnchor(1, "Do not provide medical advice")
    conflicts = naive_conflicts("forced entry into a car", [anchor])
    assert len(conflicts) == 0


def test_phase1_kill_switch_env(monkeypatch):
    """Patch 4: SW_SIGNALS_PHASE1=false should revert _detect_conflicts to v0."""
    import os
    monkeypatch.delenv("SW_SIGNALS_PHASE1", raising=False)
    assert os.getenv("SW_SIGNALS_PHASE1", "true") == "true"


def test_match_debug_has_per_anchor_votes():
    """Patch 2: build_match_debug should include per_anchor_votes with
    matcher, verdict, confidence, and explanation for each vote."""
    votes = [
        SignalVote(1, "conflict", 1.0, "naive", "keyword match"),
        SignalVote(1, "abstain", 0.0, "embedding", "no match"),
        SignalVote(2, "safe", 1.0, "naive", "safe lockout"),
    ]
    resolved, reasons = resolve_votes(votes)
    debug = build_match_debug(votes, resolved, anchor_count=2,
                             resolution_reasons=reasons)

    assert "per_anchor_votes" in debug
    rows_by_id = {row["anchor_id"]: row for row in debug["per_anchor_votes"]}

    # Anchor 1 should have 2 votes (embedding + naive), resolved to "conflict"
    assert len(rows_by_id[1]["votes"]) == 2
    assert rows_by_id[1]["votes"][0]["matcher"] == "embedding"
    assert rows_by_id[1]["votes"][0]["verdict"] == "abstain"
    assert rows_by_id[1]["votes"][1]["matcher"] == "naive"
    assert rows_by_id[1]["votes"][1]["verdict"] == "conflict"
    assert rows_by_id[1]["resolved"] == "conflict"
    assert rows_by_id[1]["resolution_reason"] == "conflict_no_safe"

    # Anchor 2 should have 1 vote (safe), resolved to "safe"
    assert len(rows_by_id[2]["votes"]) == 1
    assert rows_by_id[2]["votes"][0]["verdict"] == "safe"
    assert rows_by_id[2]["resolved"] == "safe"
    assert rows_by_id[2]["resolution_reason"] == "safe_no_conflict"


# ── Phase 2 Confidence-Aware Resolution Tests ────────────


def test_phase1_safe_overrides_regardless_of_confidence():
    """Phase 1: safe + 0.95 embedding conflict + Phase 2 off -> safe."""
    votes = [
        SignalVote(1, "safe", 1.0, "naive", "safe_lockout detected"),
        SignalVote(1, "conflict", 0.95, "embedding", "cosine similarity 0.950"),
    ]
    conflicts, reasons = resolve_votes(votes, phase2_enabled=False)
    assert 1 not in conflicts
    assert reasons[1] == "safe_overrides_conflict"


def test_phase2_high_confidence_overrides_safe():
    """Phase 2: safe + 0.91 embedding conflict -> conflict."""
    votes = [
        SignalVote(1, "safe", 1.0, "naive", "safe_lockout detected"),
        SignalVote(1, "conflict", 0.91, "embedding", "cosine similarity 0.910"),
    ]
    conflicts, reasons = resolve_votes(votes, phase2_enabled=True)
    assert conflicts[1] == "conflict"
    assert reasons[1] == "safe_overridden_by_high_confidence_embedding"


def test_phase2_low_confidence_preserves_safe():
    """Phase 2: safe + 0.72 embedding conflict -> safe."""
    votes = [
        SignalVote(1, "safe", 1.0, "naive", "safe_lockout detected"),
        SignalVote(1, "conflict", 0.72, "embedding", "cosine similarity 0.720"),
    ]
    conflicts, reasons = resolve_votes(votes, phase2_enabled=True)
    assert 1 not in conflicts
    assert reasons[1] == "safe_preserved_embedding_below_threshold"


def test_phase2_naive_conflict_cannot_override_safe():
    """Phase 2: safe + naive conflict only (no embedding) -> safe."""
    votes = [
        SignalVote(1, "safe", 1.0, "naive", "safe_lockout detected"),
        SignalVote(1, "conflict", 1.0, "naive", "keyword match"),
    ]
    conflicts, reasons = resolve_votes(votes, phase2_enabled=True)
    assert 1 not in conflicts
    assert reasons[1] == "safe_preserved_embedding_below_threshold"


def test_phase2_conflict_only_unchanged():
    """Phase 2: conflict only (no safe) -> conflict (no change)."""
    votes = [
        SignalVote(1, "conflict", 0.88, "embedding", "cosine similarity 0.880"),
        SignalVote(1, "abstain", 0.0, "naive", "no naive match"),
    ]
    conflicts, reasons = resolve_votes(votes, phase2_enabled=True)
    assert conflicts[1] == "conflict"
    assert reasons[1] == "conflict_no_safe"


def test_phase2_debug_fields_present():
    """Phase 2 debug: phase2_active + phase2_threshold in match_debug."""
    votes = [
        SignalVote(1, "conflict", 1.0, "naive", "x"),
    ]
    resolved, reasons = resolve_votes(votes, phase2_enabled=True)
    debug = build_match_debug(
        votes, resolved, anchor_count=1,
        resolution_reasons=reasons,
        phase2_active=True,
        phase2_threshold=0.85,
    )
    assert debug["phase2_active"] is True
    assert debug["phase2_threshold"] == 0.85
    assert "per_anchor_votes" in debug


def test_phase2_resolution_reason_in_per_anchor():
    """Per-anchor resolution_reason is present when Phase 2 is active."""
    votes = [
        SignalVote(1, "safe", 1.0, "naive", "safe_lockout detected"),
        SignalVote(1, "conflict", 0.91, "embedding", "cosine similarity 0.910"),
    ]
    conflicts, reasons = resolve_votes(votes, phase2_enabled=True)
    debug = build_match_debug(
        votes, conflicts, anchor_count=1,
        resolution_reasons=reasons,
        phase2_active=True,
    )
    row = debug["per_anchor_votes"][0]
    assert row["resolution_reason"] == (
        "safe_overridden_by_high_confidence_embedding"
    )
    assert row["resolved"] == "conflict"


def test_phase2_shadow_does_not_change_live_conflicts():
    """Shadow mode: resolve_votes with phase2_enabled=True computes
    Phase 2 results but they should not match Phase 1 when safe+low-conf."""
    votes = [
        SignalVote(1, "safe", 1.0, "naive", "safe_lockout detected"),
        SignalVote(1, "conflict", 0.72, "embedding", "cosine similarity 0.720"),
        SignalVote(2, "conflict", 0.90, "embedding", "cosine similarity 0.900"),
    ]

    # Phase 1 (live result)
    resolved_p1, _ = resolve_votes(votes, phase2_enabled=False)
    # Phase 2 (shadow result)
    resolved_p2, _ = resolve_votes(votes, phase2_enabled=True)

    # Anchor 1: safe in Phase 1 (safe overrides), safe in Phase 2 (below threshold)
    assert 1 not in resolved_p1
    assert 1 not in resolved_p2

    # Anchor 2: conflict in both (no safe vote)
    assert 2 in resolved_p1
    assert 2 in resolved_p2

    # would_change should be empty (no divergence in this case)
    would_change = set(resolved_p2.keys()) - set(resolved_p1.keys())
    assert would_change == set()


def test_phase2_shadow_would_change_detects_override():
    """Shadow mode: detect cases where Phase 2 would change the result."""
    votes = [
        SignalVote(1, "safe", 1.0, "naive", "safe_lockout detected"),
        SignalVote(1, "conflict", 0.91, "embedding", "cosine similarity 0.910"),
    ]

    resolved_p1, _ = resolve_votes(votes, phase2_enabled=False)
    resolved_p2, _ = resolve_votes(votes, phase2_enabled=True)

    # Phase 1: safe wins. Phase 2: embedding overrides -> conflict
    assert 1 not in resolved_p1
    assert 1 in resolved_p2

    would_change = sorted(set(resolved_p2.keys()) - set(resolved_p1.keys()))
    assert would_change == [1]


def test_phase1_debug_no_phase2_fields():
    """Phase 1 debug: phase2_active should NOT be present."""
    votes = [
        SignalVote(1, "conflict", 1.0, "naive", "x"),
    ]
    resolved, reasons = resolve_votes(votes, phase2_enabled=False)
    debug = build_match_debug(
        votes, resolved, anchor_count=1,
        resolution_reasons=reasons,
        phase2_active=False,
    )
    assert "phase2_active" not in debug
    assert "phase2_threshold" not in debug


def test_phase1_exact_backward_compat():
    """Phase 1 behaviour is byte-identical to pre-Phase-2 for all
    non-Phase-2 paths: safe+conflict->safe, conflict+abstain->conflict,
    safe_only->safe, conflict_only->conflict."""
    # safe + conflict -> safe
    r, _ = resolve_votes([
        SignalVote(1, "safe", 1.0, "naive", "s"),
        SignalVote(1, "conflict", 1.0, "embedding", "c"),
    ], phase2_enabled=False)
    assert 1 not in r

    # conflict + abstain -> conflict
    r, _ = resolve_votes([
        SignalVote(1, "conflict", 1.0, "naive", "c"),
        SignalVote(1, "abstain", 0.0, "embedding", "a"),
    ], phase2_enabled=False)
    assert r[1] == "conflict"

    # safe only -> safe
    r, _ = resolve_votes([
        SignalVote(1, "safe", 1.0, "naive", "s"),
    ], phase2_enabled=False)
    assert 1 not in r

    # conflict only -> conflict
    r, _ = resolve_votes([
        SignalVote(1, "conflict", 1.0, "naive", "c"),
    ], phase2_enabled=False)
    assert r[1] == "conflict"