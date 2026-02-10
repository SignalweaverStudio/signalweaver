from datetime import datetime, timezone
import hashlib
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import (
    Integer,
    String,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
)


class Base(DeclarativeBase):
    pass


# ============================================================
# Truth Anchors (existing — unchanged)
# ============================================================

class TruthAnchor(Base):
    __tablename__ = "truth_anchors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    level: Mapped[int] = mapped_column(Integer, index=True)  # 1..3
    statement: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(64), default="global")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )

    # backrefs for policy profiles + traces
    profiles: Mapped[list["PolicyProfileAnchor"]] = relationship(
        back_populates="anchor",
        cascade="all, delete-orphan",
    )

    trace_rows: Mapped[list["DecisionTraceAnchor"]] = relationship(
        back_populates="anchor",
        cascade="all, delete-orphan",
    )

    def stable_hash(self) -> str:
        """
        Deterministic hash of the anchor's effective policy meaning.
        If any of these fields change, the hash changes.
        """
        payload = f"{self.level}|{self.scope}|{int(bool(self.active))}|{self.statement}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


# ============================================================
# Gate Logs (existing — unchanged)
# ============================================================

class GateLog(Base):
    __tablename__ = "gate_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )

    request_summary: Mapped[str] = mapped_column(Text)

    arousal: Mapped[str] = mapped_column(String(16), default="unknown")
    dominance: Mapped[str] = mapped_column(String(16), default="unknown")

    interpretation: Mapped[str] = mapped_column(Text, default="")
    suggestion: Mapped[str] = mapped_column(Text, default="")

    decision: Mapped[str] = mapped_column(String(16))  # proceed/gate/refuse
    reason: Mapped[str] = mapped_column(String(64), default="")

    conflicted_anchor_ids: Mapped[str] = mapped_column(String(256), default="")
    user_choice: Mapped[str] = mapped_column(String(16), default="")


# ============================================================
# Policy Profiles (existing from our last step)
# ============================================================

class PolicyProfile(Base):
    __tablename__ = "policy_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )

    anchors: Mapped[list["PolicyProfileAnchor"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="PolicyProfileAnchor.priority",
    )

    traces: Mapped[list["DecisionTrace"]] = relationship(
        back_populates="policy_profile",
        cascade="all, delete-orphan",
    )


class PolicyProfileAnchor(Base):
    __tablename__ = "policy_profile_anchors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    profile_id: Mapped[int] = mapped_column(
        ForeignKey("policy_profiles.id", ondelete="CASCADE"),
        index=True,
    )

    anchor_id: Mapped[int] = mapped_column(
        ForeignKey("truth_anchors.id", ondelete="CASCADE"),
        index=True,
    )

    priority: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    profile: Mapped["PolicyProfile"] = relationship(
        back_populates="anchors"
    )

    anchor: Mapped["TruthAnchor"] = relationship(
        back_populates="profiles"
    )

    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "anchor_id",
            name="uq_profile_anchor",
        ),
    )


# ============================================================
# Decision Trace + Replay (NEW — the "damn" feature)
# ============================================================

class DecisionTrace(Base):
    __tablename__ = "decision_traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )

    # optional: tie trace to a policy profile when we implement profile selection
    policy_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("policy_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # request + normalization snapshots (audit gold)
    request_text: Mapped[str] = mapped_column(Text)
    request_normalized: Mapped[str] = mapped_column(Text, default="")

    arousal: Mapped[str] = mapped_column(String(16), default="unknown")
    dominance: Mapped[str] = mapped_column(String(16), default="unknown")

    # output snapshots (what we decided, exactly)
    decision: Mapped[str] = mapped_column(String(16))  # proceed/gate/refuse
    reason: Mapped[str] = mapped_column(String(64), default="")
    explanation: Mapped[str] = mapped_column(Text, default="")

    # freeform JSON-as-text for per-anchor match details (keep SQLite-simple)
    match_debug_json: Mapped[str] = mapped_column(Text, default="")

    policy_profile: Mapped["PolicyProfile"] = relationship(
        back_populates="traces"
    )

    anchors: Mapped[list["DecisionTraceAnchor"]] = relationship(
        back_populates="trace",
        cascade="all, delete-orphan",
        order_by="DecisionTraceAnchor.anchor_id",
    )


class DecisionTraceAnchor(Base):
    __tablename__ = "decision_trace_anchors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    trace_id: Mapped[int] = mapped_column(
        ForeignKey("decision_traces.id", ondelete="CASCADE"),
        index=True,
    )

    anchor_id: Mapped[int] = mapped_column(
        ForeignKey("truth_anchors.id", ondelete="CASCADE"),
        index=True,
    )

    # snapshot/hash for drift detection
    anchor_hash: Mapped[str] = mapped_column(String(64), index=True)
    level_snapshot: Mapped[int] = mapped_column(Integer)
    scope_snapshot: Mapped[str] = mapped_column(String(64))
    active_snapshot: Mapped[bool] = mapped_column(Boolean)
    statement_snapshot: Mapped[str] = mapped_column(Text)

    # optional match info (populate if available)
    matched: Mapped[bool] = mapped_column(Boolean, default=False)
    match_note: Mapped[str] = mapped_column(Text, default="")

    trace: Mapped["DecisionTrace"] = relationship(
        back_populates="anchors"
    )

    anchor: Mapped["TruthAnchor"] = relationship(
        back_populates="trace_rows"
    )

    __table_args__ = (
        UniqueConstraint(
            "trace_id",
            "anchor_id",
            name="uq_trace_anchor",
        ),
    )
