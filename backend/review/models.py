from datetime import datetime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, Text, String, Boolean, DateTime


class Base(DeclarativeBase):
    pass


class TruthAnchor(Base):
    __tablename__ = "truth_anchors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    level: Mapped[int] = mapped_column(Integer, index=True)  # 1..3
    statement: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(64), default="global")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GateLog(Base):
    __tablename__ = "gate_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    request_summary: Mapped[str] = mapped_column(Text)

    arousal: Mapped[str] = mapped_column(String(16), default="unknown")
    dominance: Mapped[str] = mapped_column(String(16), default="unknown")

    decision: Mapped[str] = mapped_column(String(16))  # proceed/gate/refuse
    reason: Mapped[str] = mapped_column(String(64), default="")

    conflicted_anchor_ids: Mapped[str] = mapped_column(String(256), default="")
    user_choice: Mapped[str] = mapped_column(String(16), default="")

