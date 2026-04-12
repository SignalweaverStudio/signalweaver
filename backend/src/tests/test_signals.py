from app.signals import (
    SignalVote,
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
        "I am legally locked out, a locksmith can help, please avoid forced entry",
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


def test_resolve_votes_safe_overrides_conflict():
    votes = [
        SignalVote(1, "conflict", 0.8, "embedding", "semantic match"),
        SignalVote(1, "safe", 1.0, "naive", "safe lockout"),
    ]

    resolved = resolve_votes(votes)
    assert 1 not in resolved


def test_resolve_votes_conflict_beats_abstain():
    votes = [
        SignalVote(1, "conflict", 1.0, "naive", "keyword match"),
        SignalVote(1, "abstain", 0.0, "embedding", "no match"),
    ]

    resolved = resolve_votes(votes)
    assert resolved[1] == "conflict"


def test_build_match_debug_sorted():
    votes = [
        SignalVote(5, "conflict", 1.0, "naive", "x"),
        SignalVote(1, "abstain", 0.0, "embedding", "y"),
        SignalVote(1, "conflict", 1.0, "naive", "z"),
    ]

    resolved = resolve_votes(votes)
    debug = build_match_debug(votes, resolved, anchor_count=2)

    assert debug["matcher_mode"] == "signals_v1"
    assert debug["conflicted_ids"] == [1, 5]
    assert [row["anchor_id"] for row in debug["per_anchor_votes"]] == [1, 5]