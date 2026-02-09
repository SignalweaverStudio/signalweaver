from datetime import datetime, timezone
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

    # optional backref for profiles
    profiles: Mapped[list["PolicyProfileAnchor"]] = relationship(
        back_populates="anchor",
        cascade="all, delete-orphan",
    )


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
# Policy Profiles (NEW — architecture evolution layer)
# =================================================
