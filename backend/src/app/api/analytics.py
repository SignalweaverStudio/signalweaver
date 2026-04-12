"""
Execution Analytics & Observability Layer (Stage 16 + Stage 19 + Stage 20 + Stage 21)

Read-only, additive API that turns SignalWeaver's stored data into
operational insight. No new tables (except Stage 21 audit log), no
background jobs, no caching.

Endpoints:
  GET /executions            — paginated execution history
  GET /executions/summary    — aggregate governance metrics
  GET /executions/timeseries — time-bucketed governance trends
  GET /governance/insights   — top conflicted anchors & block reasons
  GET /compliance/export     — full audit chain for a date range
  GET /alerts                — governance anomaly detection (thresholds + spikes)
  POST /alerts/dispatch      — push alerts to external webhook (Stage 21)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session

from app.security import verify_api_key, rate_limit
from app.db import get_db
from app.auth import get_tenant
from app.models import (
    Tenant,
    ExecutionLog,
    DecisionTrace,
    DecisionTraceAnchor,
    AlertDispatchLog,
)
from app.schemas import (
    ExecutionHistoryItem,
    ExecutionHistoryOut,
    ExecutionSummaryOut,
    TimeseriesBucketItem,
    TimeseriesOut,
    ConflictedAnchorEntry,
    TopReasonEntry,
    GovernanceInsightsOut,
    ComplianceTraceItem,
    ComplianceExportOut,
    AlertItem,
    AlertsOut,
    AlertDispatchIn,
    AlertDispatchOut,
    parse_id_list,
)


router = APIRouter(
    dependencies=[Depends(verify_api_key)],
)


def _rl(request: Request):
    rate_limit(request, limit=120, window_s=60)


router.dependencies.append(Depends(_rl))


# ============================================================
# 1. Execution History
# ============================================================

@router.get("/executions", response_model=ExecutionHistoryOut)
def execution_history(
    status: Optional[str] = Query(
        default=None, description="Filter: executed | blocked"
    ),
    connector: Optional[str] = Query(
        default=None, description="Filter by connector name"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_tenant),
):
    """
    Paginated execution history, newest-first. Scoped to tenant.
    """
    base_where = [ExecutionLog.tenant_id == tenant.id]

    if status is not None:
        if status not in ("executed", "blocked"):
            raise HTTPException(
                status_code=422,
                detail="status must be 'executed' or 'blocked'",
            )
        base_where.append(ExecutionLog.status == status)

    if connector is not None:
        base_where.append(ExecutionLog.connector == connector)

    # Count
    count_stmt = (
        select(func.count())
        .select_from(ExecutionLog)
        .where(*base_where)
    )
    total = db.scalar(count_stmt) or 0

    # Fetch rows joined with DecisionTrace for would_block
    stmt = (
        select(ExecutionLog, DecisionTrace.would_block)
        .outerjoin(DecisionTrace, ExecutionLog.trace_id == DecisionTrace.id)
        .where(*base_where)
        .order_by(ExecutionLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = db.execute(stmt).all()

    items: List[ExecutionHistoryItem] = []
    for exec_log, would_block in rows:
        items.append(
            ExecutionHistoryItem(
                trace_id=exec_log.trace_id or 0,
                decision=exec_log.decision,
                status=exec_log.status,
                connector=exec_log.connector,
                created_at=exec_log.created_at,
                would_block=bool(would_block) if would_block is not None else False,
            )
        )

    return ExecutionHistoryOut(total=total, items=items)


# ============================================================
# 2. Summary Metrics
# ============================================================

@router.get("/executions/summary", response_model=ExecutionSummaryOut)
def execution_summary(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_tenant),
):
    """
    Aggregate governance metrics derived from ExecutionLog + DecisionTrace.
    """
    tenant_filter = [ExecutionLog.tenant_id == tenant.id]

    total_requests = db.scalar(
        select(func.count()).select_from(ExecutionLog).where(*tenant_filter)
    ) or 0

    executed = db.scalar(
        select(func.count())
        .select_from(ExecutionLog)
        .where(*tenant_filter, ExecutionLog.status == "executed")
    ) or 0

    blocked = db.scalar(
        select(func.count())
        .select_from(ExecutionLog)
        .where(*tenant_filter, ExecutionLog.status == "blocked")
    ) or 0

    failed = db.scalar(
        select(func.count())
        .select_from(ExecutionLog)
        .where(*tenant_filter, ExecutionLog.status == "failed")
    ) or 0

    block_rate = round(blocked / total_requests, 4) if total_requests > 0 else 0.0

    # Override rate: traces with non-empty override_reason and decision != proceed
    # Join ExecutionLog → DecisionTrace to get override_reason
    override_count = db.scalar(
        select(func.count())
        .select_from(ExecutionLog)
        .join(DecisionTrace, ExecutionLog.trace_id == DecisionTrace.id)
        .where(
            *tenant_filter,
            DecisionTrace.override_reason != "",
            DecisionTrace.override_reason.isnot(None),
            DecisionTrace.decision != "proceed",
        )
    ) or 0
    override_rate = round(override_count / total_requests, 4) if total_requests > 0 else 0.0

    # Shadow would-block rate: fraction of traces where would_block=True
    shadow_count = db.scalar(
        select(func.count())
        .select_from(ExecutionLog)
        .join(DecisionTrace, ExecutionLog.trace_id == DecisionTrace.id)
        .where(*tenant_filter, DecisionTrace.would_block == True)  # noqa: E712
    ) or 0
    shadow_would_block_rate = (
        round(shadow_count / total_requests, 4) if total_requests > 0 else 0.0
    )

    return ExecutionSummaryOut(
        total_requests=total_requests,
        executed=executed,
        blocked=blocked,
        failed=failed,
        block_rate=block_rate,
        override_rate=override_rate,
        shadow_would_block_rate=shadow_would_block_rate,
    )


# ============================================================
# 3. Governance Insights
# ============================================================

@router.get("/governance/insights", response_model=GovernanceInsightsOut)
def governance_insights(
    limit: int = Query(10, ge=1, le=50, description="Max entries per category"),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_tenant),
):
    """
    Top triggering anchors and most common block reasons.
    Derived from DecisionTraceAnchor and DecisionTrace for this tenant.
    """
    # Top conflicted anchors: anchors with matched=True, grouped by anchor_id
    top_anchors_stmt = (
        select(
            DecisionTraceAnchor.anchor_id,
            func.count().label("cnt"),
        )
        .join(DecisionTrace, DecisionTraceAnchor.trace_id == DecisionTrace.id)
        .where(
            DecisionTrace.tenant_id == tenant.id,
            DecisionTraceAnchor.matched == True,  # noqa: E712
        )
        .group_by(DecisionTraceAnchor.anchor_id)
        .order_by(text("cnt DESC"))
        .limit(limit)
    )
    anchor_rows = db.execute(top_anchors_stmt).all()
    top_conflicted_anchors = [
        ConflictedAnchorEntry(anchor_id=row.anchor_id, count=row.cnt)
        for row in anchor_rows
    ]

    # Top block reasons: from DecisionTrace where decision != proceed
    top_reasons_stmt = (
        select(
            DecisionTrace.reason,
            func.count().label("cnt"),
        )
        .where(
            DecisionTrace.tenant_id == tenant.id,
            DecisionTrace.decision != "proceed",
        )
        .group_by(DecisionTrace.reason)
        .order_by(text("cnt DESC"))
        .limit(limit)
    )
    reason_rows = db.execute(top_reasons_stmt).all()
    top_reasons = [
        TopReasonEntry(reason=row.reason, count=row.cnt)
        for row in reason_rows
    ]

    return GovernanceInsightsOut(
        top_conflicted_anchors=top_conflicted_anchors,
        top_reasons=top_reasons,
    )


# ============================================================
# 4. Compliance Export
# ============================================================

@router.get("/compliance/export", response_model=ComplianceExportOut)
def compliance_export(
    start_date: Optional[datetime] = Query(
        default=None,
        description="Start of date range (inclusive). ISO timestamp.",
    ),
    end_date: Optional[datetime] = Query(
        default=None,
        description="End of date range (inclusive). ISO timestamp.",
    ),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_tenant),
):
    """
    Export decision traces with execution outcomes for compliance auditing.
    Returns the full audit chain: trace → anchors → execution.
    """
    base_where = [DecisionTrace.tenant_id == tenant.id]

    if start_date is not None:
        base_where.append(DecisionTrace.created_at >= start_date)
    if end_date is not None:
        base_where.append(DecisionTrace.created_at <= end_date)

    # Count
    total = db.scalar(
        select(func.count())
        .select_from(DecisionTrace)
        .where(*base_where)
    ) or 0

    # Fetch traces with left join to ExecutionLog
    stmt = (
        select(
            DecisionTrace,
            ExecutionLog.status.label("exec_status"),
            ExecutionLog.connector.label("exec_connector"),
        )
        .outerjoin(ExecutionLog, ExecutionLog.trace_id == DecisionTrace.id)
        .where(*base_where)
        .order_by(DecisionTrace.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = db.execute(stmt).all()

    # Batch-load conflicted anchor IDs for the returned trace IDs
    trace_ids = [r.DecisionTrace.id for r in rows]
    conflicted_map: dict[int, List[int]] = {}

    if trace_ids:
        anchor_stmt = (
            select(
                DecisionTraceAnchor.trace_id,
                DecisionTraceAnchor.anchor_id,
            )
            .where(
                DecisionTraceAnchor.trace_id.in_(trace_ids),
                DecisionTraceAnchor.matched == True,  # noqa: E712
            )
        )
        anchor_rows = db.execute(anchor_stmt).all()
        for ar in anchor_rows:
            conflicted_map.setdefault(ar.trace_id, []).append(ar.anchor_id)

    traces: List[ComplianceTraceItem] = []
    for r in rows:
        trace = r.DecisionTrace
        traces.append(
            ComplianceTraceItem(
                trace_id=trace.id,
                created_at=trace.created_at,
                request_text=trace.request_text,
                decision=trace.decision,
                reason=trace.reason,
                explanation=trace.explanation or "",
                enforcement_mode=trace.enforcement_mode_snapshot or "hard",
                would_block=bool(trace.would_block),
                conflicted_anchor_ids=conflicted_map.get(trace.id, []),
                execution_status=r.exec_status,
                execution_connector=r.exec_connector,
            )
        )

    return ComplianceExportOut(
        total=total,
        start_date=start_date,
        end_date=end_date,
        traces=traces,
    )


# ============================================================
# 5. Time-Series Metrics (Stage 19)
# ============================================================

VALID_GRANULARITIES = {"hour", "day", "week"}

# Cap on the number of buckets to prevent abuse (e.g. hourly over 1 year = 8760)
MAX_BUCKETS = 366


def _truncate_to_granularity(dt: datetime, granularity: str) -> datetime:
    """
    Truncate a datetime to the start of its bucket based on granularity.

    - hour: truncate to top of the hour
    - day:  truncate to midnight UTC
    - week: truncate to Monday 00:00 UTC (ISO week start)
    """
    dt_utc = dt.replace(tzinfo=None) if dt.tzinfo else dt
    if granularity == "hour":
        return dt_utc.replace(minute=0, second=0, microsecond=0)
    elif granularity == "day":
        return dt_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    elif granularity == "week":
        # ISO week: Monday = weekday 0
        days_since_monday = dt_utc.weekday()
        monday = dt_utc - timedelta(days=days_since_monday)
        return monday.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        return dt_utc


def _generate_buckets(
    start: datetime,
    end: datetime,
    granularity: str,
) -> List[Tuple[datetime, datetime]]:
    """
    Generate a list of (bucket_start, bucket_end) tuples covering [start, end).

    Each bucket covers [bucket_start, bucket_end) — inclusive start, exclusive end.
    The first bucket starts at the calendar-aligned boundary of *start* (which
    may be before *start*). This keeps bucket boundaries aligned to natural
    boundaries (midnight, Monday, top-of-hour) even when the request range
    doesn't start exactly on a boundary.
    """
    buckets: List[Tuple[datetime, datetime]] = []
    current = _truncate_to_granularity(start, granularity)

    if granularity == "hour":
        delta = timedelta(hours=1)
    elif granularity == "day":
        delta = timedelta(days=1)
    else:  # week
        delta = timedelta(weeks=1)

    while current < end:
        bucket_end = current + delta
        # Don't overshoot end
        if bucket_end > end:
            bucket_end = end
        buckets.append((current, bucket_end))
        current = bucket_end

    return buckets


def _compute_bucket_metrics(
    db: Session,
    tenant_id: int,
    bucket_start: datetime,
    bucket_end: datetime,
    connector_filter: Optional[str],
    status_filter: Optional[str],
) -> dict:
    """
    Compute governance metrics for a single time bucket.

    Returns a dict with: total_requests, executed, blocked, failed,
    override_count, shadow_would_block_count.
    """
    base_where = [
        ExecutionLog.tenant_id == tenant_id,
        ExecutionLog.created_at >= bucket_start,
        ExecutionLog.created_at < bucket_end,
    ]

    if connector_filter is not None:
        base_where.append(ExecutionLog.connector == connector_filter)
    if status_filter is not None:
        base_where.append(ExecutionLog.status == status_filter)

    # If status filter is applied, all counts come from one query
    # If no status filter, we need counts per status
    total_requests = db.scalar(
        select(func.count()).select_from(ExecutionLog).where(*base_where)
    ) or 0

    if status_filter is not None:
        executed = total_requests if status_filter == "executed" else 0
        blocked = total_requests if status_filter == "blocked" else 0
        failed = total_requests if status_filter == "failed" else 0
    else:
        executed = db.scalar(
            select(func.count())
            .select_from(ExecutionLog)
            .where(*base_where, ExecutionLog.status == "executed")
        ) or 0
        blocked = db.scalar(
            select(func.count())
            .select_from(ExecutionLog)
            .where(*base_where, ExecutionLog.status == "blocked")
        ) or 0
        failed = db.scalar(
            select(func.count())
            .select_from(ExecutionLog)
            .where(*base_where, ExecutionLog.status == "failed")
        ) or 0

    # Override and shadow metrics require joining DecisionTrace
    override_count = 0
    shadow_count = 0

    if total_requests > 0:
        trace_where = base_where.copy()

        override_count = db.scalar(
            select(func.count())
            .select_from(ExecutionLog)
            .join(DecisionTrace, ExecutionLog.trace_id == DecisionTrace.id)
            .where(
                *trace_where,
                DecisionTrace.override_reason != "",
                DecisionTrace.override_reason.isnot(None),
                DecisionTrace.decision != "proceed",
            )
        ) or 0

        shadow_count = db.scalar(
            select(func.count())
            .select_from(ExecutionLog)
            .join(DecisionTrace, ExecutionLog.trace_id == DecisionTrace.id)
            .where(*trace_where, DecisionTrace.would_block == True)  # noqa: E712
        ) or 0

    return {
        "total_requests": total_requests,
        "executed": executed,
        "blocked": blocked,
        "failed": failed,
        "override_count": override_count,
        "shadow_would_block_count": shadow_count,
    }


@router.get("/executions/timeseries", response_model=TimeseriesOut)
def execution_timeseries(
    granularity: str = Query(
        ..., description="Time bucket granularity: hour | day | week"
    ),
    start_date: Optional[datetime] = Query(
        default=None,
        description="Start of range (inclusive). ISO timestamp. Default: 7 days ago.",
    ),
    end_date: Optional[datetime] = Query(
        default=None,
        description="End of range (inclusive). ISO timestamp. Default: now.",
    ),
    connector: Optional[str] = Query(
        default=None, description="Filter by connector name"
    ),
    status: Optional[str] = Query(
        default=None, description="Filter by execution status"
    ),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_tenant),
):
    """
    Time-bucketed governance metrics.

    Returns per-bucket counts and rates for total_requests, executed, blocked,
    failed, block_rate, override_rate, and shadow_would_block_rate.

    Bucket boundaries are aligned to calendar boundaries:
      - hour: top of each hour (00:00, 01:00, ...)
      - day:  midnight UTC (00:00)
      - week: Monday 00:00 UTC

    Defaults to the last 7 days when no dates are provided.
    """
    if granularity not in VALID_GRANULARITIES:
        raise HTTPException(
            status_code=422,
            detail=f"granularity must be one of: {', '.join(sorted(VALID_GRANULARITIES))}",
        )

    now = datetime.now(timezone.utc)
    end = end_date.astimezone(timezone.utc).replace(tzinfo=None) if end_date else now.replace(tzinfo=None)
    start = (
        start_date.astimezone(timezone.utc).replace(tzinfo=None)
        if start_date
        else end - timedelta(days=7)
    )

    if start >= end:
        raise HTTPException(
            status_code=422,
            detail="start_date must be before end_date",
        )

    buckets = _generate_buckets(start, end, granularity)

    if len(buckets) > MAX_BUCKETS:
        raise HTTPException(
            status_code=422,
            detail=f"Requested range produces {len(buckets)} buckets, "
                   f"exceeding the maximum of {MAX_BUCKETS}. "
                   f"Use a narrower date range or coarser granularity.",
        )

    result_buckets: List[TimeseriesBucketItem] = []
    for bucket_start, bucket_end in buckets:
        metrics = _compute_bucket_metrics(
            db=db,
            tenant_id=tenant.id,
            bucket_start=bucket_start,
            bucket_end=bucket_end,
            connector_filter=connector,
            status_filter=status,
        )

        total = metrics["total_requests"]
        result_buckets.append(
            TimeseriesBucketItem(
                start=bucket_start,
                end=bucket_end,
                total_requests=total,
                executed=metrics["executed"],
                blocked=metrics["blocked"],
                failed=metrics["failed"],
                block_rate=round(metrics["blocked"] / total, 4) if total > 0 else 0.0,
                override_rate=(
                    round(metrics["override_count"] / total, 4) if total > 0 else 0.0
                ),
                shadow_would_block_rate=(
                    round(metrics["shadow_would_block_count"] / total, 4)
                    if total > 0
                    else 0.0
                ),
            )
        )

    return TimeseriesOut(granularity=granularity, buckets=result_buckets)


# ============================================================
# 6. Alerting Layer (Stage 20)
# ============================================================

# Window parsing pattern: optional number followed by h/d (e.g. 1h, 24h, 7d)
_WINDOW_RE = re.compile(r"^(?:(\d+)\s*(h|d))?$", re.IGNORECASE)

# Default thresholds
DEFAULT_BLOCK_RATE_THRESHOLD = 0.25
DEFAULT_OVERRIDE_RATE_THRESHOLD = 0.10
DEFAULT_FAILURE_RATE_THRESHOLD = 0.05
DEFAULT_SPIKE_MULTIPLIER = 2.0

# Minimum number of requests in a window to evaluate alerts
# Prevents false positives from tiny sample sizes
_MIN_REQUESTS_FOR_ALERTS = 5

# Minimum volume in a bucket to consider it for spike detection
# Prevents spike alerts when going from 0→1 request
_MIN_BUCKET_VOLUME_FOR_SPIKE = 3


def _parse_window(window: str) -> Tuple[timedelta, str]:
    """
    Parse a window string like '1h', '24h', '7d' into a timedelta.

    Returns (timedelta, normalized_window_string).
    Raises HTTPException 422 on invalid format.
    """
    m = _WINDOW_RE.match(window.strip())
    if not m:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid window format: '{window}'. "
                f"Expected format: <number><h|d> (e.g. '1h', '24h', '7d'). "
                f"Default: '24h'."
            ),
        )
    num_str, unit = m.group(1), m.group(2).lower()
    num = int(num_str) if num_str else 24  # default 24h

    if num <= 0:
        raise HTTPException(
            status_code=422,
            detail=f"Window duration must be positive, got '{window}'.",
        )

    if unit == "h":
        if num > 720:  # 30 days max
            raise HTTPException(
                status_code=422,
                detail="Window too large. Maximum: 720h (30 days).",
            )
        return timedelta(hours=num), f"{num}h"
    else:  # d
        if num > 30:
            raise HTTPException(
                status_code=422,
                detail="Window too large. Maximum: 30d.",
            )
        return timedelta(days=num), f"{num}d"


def _choose_granularity(window_delta: timedelta) -> str:
    """
    Pick a sensible default granularity based on the window size.

    - <= 2h  → hour
    - <= 7d  → day
    - >  7d  → week
    """
    total_hours = window_delta.total_seconds() / 3600
    if total_hours <= 2:
        return "hour"
    elif total_hours <= 168:  # 7 days
        return "day"
    else:
        return "week"


def _evaluate_alerts(
    buckets: List[TimeseriesBucketItem],
    block_rate_threshold: float,
    override_rate_threshold: float,
    failure_rate_threshold: float,
    spike_multiplier: float,
) -> List[AlertItem]:
    """
    Evaluate alert conditions against a list of timeseries buckets.

    Window-level alerts compare the aggregate across all buckets.
    Spike alerts compare the latest bucket against the average of previous buckets.

    Returns a list of AlertItem for any triggered conditions.
    """
    alerts: List[AlertItem] = []

    # --- Window-level aggregate ---
    total_requests = sum(b.total_requests for b in buckets)
    if total_requests < _MIN_REQUESTS_FOR_ALERTS:
        return alerts  # Not enough data to evaluate meaningfully

    total_executed = sum(b.executed for b in buckets)
    total_blocked = sum(b.blocked for b in buckets)
    total_failed = sum(b.failed for b in buckets)
    total_override = sum(
        round(b.override_rate * b.total_requests, 4) if b.total_requests > 0 else 0
        for b in buckets
    )

    window_block_rate = total_blocked / total_requests if total_requests > 0 else 0.0
    window_override_rate = total_override / total_requests if total_requests > 0 else 0.0
    window_failure_rate = total_failed / total_requests if total_requests > 0 else 0.0

    # 1. High block rate
    if window_block_rate > block_rate_threshold:
        alerts.append(
            AlertItem(
                type="high_block_rate",
                value=round(window_block_rate, 4),
                threshold=block_rate_threshold,
            )
        )

    # 2. High override rate
    if window_override_rate > override_rate_threshold:
        alerts.append(
            AlertItem(
                type="high_override_rate",
                value=round(window_override_rate, 4),
                threshold=override_rate_threshold,
            )
        )

    # 3. High failure rate
    if window_failure_rate > failure_rate_threshold:
        alerts.append(
            AlertItem(
                type="high_failure_rate",
                value=round(window_failure_rate, 4),
                threshold=failure_rate_threshold,
            )
        )

    # --- Spike detection ---
    if len(buckets) >= 2:
        latest = buckets[-1]
        previous = buckets[:-1]

        # Filter previous buckets that have enough volume
        meaningful_previous = [
            b for b in previous if b.total_requests >= _MIN_BUCKET_VOLUME_FOR_SPIKE
        ]

        if meaningful_previous and latest.total_requests >= _MIN_BUCKET_VOLUME_FOR_SPIKE:
            # Check spike in block_rate
            prev_avg_block = sum(
                b.block_rate for b in meaningful_previous
            ) / len(meaningful_previous)

            if prev_avg_block > 0 and latest.block_rate > prev_avg_block * spike_multiplier:
                alerts.append(
                    AlertItem(
                        type="spike_detected",
                        metric="block_rate",
                        value=round(latest.block_rate, 4),
                        threshold=round(prev_avg_block * spike_multiplier, 4),
                        previous_avg=round(prev_avg_block, 4),
                    )
                )

            # Check spike in failure rate
            prev_avg_failure = sum(
                (b.failed / b.total_requests if b.total_requests > 0 else 0)
                for b in meaningful_previous
            ) / len(meaningful_previous)

            if prev_avg_failure > 0 and (
                latest.failed / latest.total_requests if latest.total_requests > 0 else 0
            ) > prev_avg_failure * spike_multiplier:
                alerts.append(
                    AlertItem(
                        type="spike_detected",
                        metric="failure_rate",
                        value=round(
                            latest.failed / latest.total_requests
                            if latest.total_requests > 0
                            else 0,
                            4,
                        ),
                        threshold=round(prev_avg_failure * spike_multiplier, 4),
                        previous_avg=round(prev_avg_failure, 4),
                    )
                )

    return alerts


@router.get("/alerts", response_model=AlertsOut)
def get_alerts(
    window: str = Query(
        default="24h",
        description="Time window: e.g. '1h', '24h', '7d'. Default: '24h'.",
    ),
    granularity: Optional[str] = Query(
        default=None,
        description=(
            "Bucket granularity: hour | day | week. "
            "Auto-selected based on window if not provided."
        ),
    ),
    connector: Optional[str] = Query(
        default=None, description="Filter by connector name"
    ),
    status: Optional[str] = Query(
        default=None, description="Filter by execution status"
    ),
    block_rate_threshold: Optional[float] = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description=f"Block rate threshold (0-1). Default: {DEFAULT_BLOCK_RATE_THRESHOLD}",
    ),
    override_rate_threshold: Optional[float] = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description=f"Override rate threshold (0-1). Default: {DEFAULT_OVERRIDE_RATE_THRESHOLD}",
    ),
    failure_rate_threshold: Optional[float] = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description=f"Failure rate threshold (0-1). Default: {DEFAULT_FAILURE_RATE_THRESHOLD}",
    ),
    spike_multiplier: Optional[float] = Query(
        default=None,
        ge=1.0,
        le=100.0,
        description=f"Spike detection multiplier. Default: {DEFAULT_SPIKE_MULTIPLIER}",
    ),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_tenant),
):
    """
    Evaluate governance anomalies over a time window.

    Computes time-bucketed metrics, then checks:
      - High block rate (window aggregate)
      - High override rate (window aggregate)
      - High failure rate (window aggregate)
      - Spike detection (latest bucket vs previous average)

    Returns alert signals with overall status ('ok' or 'alert').
    No background jobs, no state — pure "alerts on demand".
    """
    # Parse and validate window
    window_delta, normalized_window = _parse_window(window)

    # Resolve thresholds
    brt = block_rate_threshold if block_rate_threshold is not None else DEFAULT_BLOCK_RATE_THRESHOLD
    ort = override_rate_threshold if override_rate_threshold is not None else DEFAULT_OVERRIDE_RATE_THRESHOLD
    frt = failure_rate_threshold if failure_rate_threshold is not None else DEFAULT_FAILURE_RATE_THRESHOLD
    sm = spike_multiplier if spike_multiplier is not None else DEFAULT_SPIKE_MULTIPLIER

    # Resolve granularity
    if granularity is not None:
        if granularity not in VALID_GRANULARITIES:
            raise HTTPException(
                status_code=422,
                detail=f"granularity must be one of: {', '.join(sorted(VALID_GRANULARITIES))}",
            )
    else:
        granularity = _choose_granularity(window_delta)

    # Compute date range from window
    now = datetime.now(timezone.utc)
    end = now.replace(tzinfo=None)
    start = end - window_delta

    # Generate buckets and compute metrics (reuse existing helpers)
    buckets_spec = _generate_buckets(start, end, granularity)

    result_buckets: List[TimeseriesBucketItem] = []
    for bucket_start, bucket_end in buckets_spec:
        metrics = _compute_bucket_metrics(
            db=db,
            tenant_id=tenant.id,
            bucket_start=bucket_start,
            bucket_end=bucket_end,
            connector_filter=connector,
            status_filter=status,
        )

        total = metrics["total_requests"]
        result_buckets.append(
            TimeseriesBucketItem(
                start=bucket_start,
                end=bucket_end,
                total_requests=total,
                executed=metrics["executed"],
                blocked=metrics["blocked"],
                failed=metrics["failed"],
                block_rate=round(metrics["blocked"] / total, 4) if total > 0 else 0.0,
                override_rate=(
                    round(metrics["override_count"] / total, 4) if total > 0 else 0.0
                ),
                shadow_would_block_rate=(
                    round(metrics["shadow_would_block_count"] / total, 4)
                    if total > 0
                    else 0.0
                ),
            )
        )

    # Evaluate alert conditions
    triggered = _evaluate_alerts(
        buckets=result_buckets,
        block_rate_threshold=brt,
        override_rate_threshold=ort,
        failure_rate_threshold=frt,
        spike_multiplier=sm,
    )

    return AlertsOut(
        window=normalized_window,
        alerts=triggered,
        status="alert" if triggered else "ok",
    )


# ============================================================
# 7. Alert Dispatch (Stage 21)
# ============================================================

def _compute_alerts_for_dispatch(
    db: Session,
    tenant_id: int,
    window: str,
    granularity: Optional[str],
    connector_filter: Optional[str],
    status_filter: Optional[str],
    block_rate_threshold: float,
    override_rate_threshold: float,
    failure_rate_threshold: float,
    spike_multiplier: float,
) -> Tuple[List[AlertItem], str, str]:
    """
    Shared helper that computes alert signals using the same logic as GET /alerts.

    Returns (triggered_alerts, normalized_window, resolved_granularity).

    This is the single source of truth for alert computation, used by both
    GET /alerts and POST /alerts/dispatch.
    """
    window_delta, normalized_window = _parse_window(window)

    # Resolve granularity
    if granularity is not None:
        if granularity not in VALID_GRANULARITIES:
            raise HTTPException(
                status_code=422,
                detail=f"granularity must be one of: {', '.join(sorted(VALID_GRANULARITIES))}",
            )
    else:
        granularity = _choose_granularity(window_delta)

    # Compute date range from window
    now = datetime.now(timezone.utc)
    end = now.replace(tzinfo=None)
    start = end - window_delta

    # Generate buckets and compute metrics
    buckets_spec = _generate_buckets(start, end, granularity)

    result_buckets: List[TimeseriesBucketItem] = []
    for bucket_start, bucket_end in buckets_spec:
        metrics = _compute_bucket_metrics(
            db=db,
            tenant_id=tenant_id,
            bucket_start=bucket_start,
            bucket_end=bucket_end,
            connector_filter=connector_filter,
            status_filter=status_filter,
        )

        total = metrics["total_requests"]
        result_buckets.append(
            TimeseriesBucketItem(
                start=bucket_start,
                end=bucket_end,
                total_requests=total,
                executed=metrics["executed"],
                blocked=metrics["blocked"],
                failed=metrics["failed"],
                block_rate=round(metrics["blocked"] / total, 4) if total > 0 else 0.0,
                override_rate=(
                    round(metrics["override_count"] / total, 4) if total > 0 else 0.0
                ),
                shadow_would_block_rate=(
                    round(metrics["shadow_would_block_count"] / total, 4)
                    if total > 0
                    else 0.0
                ),
            )
        )

    # Evaluate alert conditions
    triggered = _evaluate_alerts(
        buckets=result_buckets,
        block_rate_threshold=block_rate_threshold,
        override_rate_threshold=override_rate_threshold,
        failure_rate_threshold=failure_rate_threshold,
        spike_multiplier=spike_multiplier,
    )

    return triggered, normalized_window, granularity


def _build_outbound_payload(
    tenant_id: int,
    window: str,
    granularity: str,
    alerts: List[AlertItem],
) -> dict:
    """
    Build the structured outbound webhook payload for alert delivery.

    This payload is sent to the external webhook target. It is designed
    to be concise, JSON-only, and suitable for downstream systems.
    """
    return {
        "tenant_id": tenant_id,
        "window": window,
        "granularity": granularity,
        "status": "alert",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "alerts": [a.model_dump(exclude_none=True) for a in alerts],
    }


@router.post("/alerts/dispatch", response_model=AlertDispatchOut)
def dispatch_alerts(
    body: AlertDispatchIn,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_tenant),
):
    """
    Compute alerts and push them to an external webhook target.

    This is a synchronous, on-demand alert delivery mechanism. It:
      1. Computes alerts using the same logic as GET /alerts
      2. If alerts exist, sends them to the configured webhook target
      3. Writes an audit record to AlertDispatchLog

    No schedulers, no background jobs, no retries.
    This is "press the button, get the alerts delivered".

    Failure semantics:
      - No alerts found → dispatch_status = "not_sent"
      - Alerts present + webhook succeeds (2xx) → dispatch_status = "sent"
      - Alerts present + webhook fails → dispatch_status = "failed"
    """
    from app.connectors.webhook import WebhookConnector
    from app.connectors.redaction import redact_sensitive

    # --- 1. Compute alerts (reuse single source of truth) ---
    triggered, normalized_window, resolved_granularity = _compute_alerts_for_dispatch(
        db=db,
        tenant_id=tenant.id,
        window=body.window,
        granularity=body.granularity,
        connector_filter=body.connector_filter,
        status_filter=body.status_filter,
        block_rate_threshold=body.block_rate_threshold,
        override_rate_threshold=body.override_rate_threshold,
        failure_rate_threshold=body.failure_rate_threshold,
        spike_multiplier=body.spike_multiplier,
    )

    alert_status = "alert" if triggered else "ok"
    alert_count = len(triggered)

    # --- 2. If no alerts, skip dispatch ---
    if not triggered:
        # Write audit record
        audit = AlertDispatchLog(
            tenant_id=tenant.id,
            alert_status="ok",
            alert_count=0,
            dispatch_status="not_sent",
            connector="webhook",
            result_json="",
        )
        db.add(audit)
        db.commit()

        return AlertDispatchOut(
            status="ok",
            alert_count=0,
            dispatch_status="not_sent",
            connector="webhook",
            result=None,
        )

    # --- 3. Build outbound payload ---
    outbound_payload = _build_outbound_payload(
        tenant_id=tenant.id,
        window=normalized_window,
        granularity=resolved_granularity,
        alerts=triggered,
    )

    # --- 4. Dispatch via WebhookConnector ---
    # Construct the connector request in the same format as the execution layer.
    # The WebhookConnector expects context with url, method, headers, payload, etc.
    # We inject the alert payload as the webhook payload.
    connector_request = {
        "raw_text": "alert-dispatch",
        "context": {
            **body.context,
            "payload": outbound_payload,
        },
    }

    connector = WebhookConnector()
    connector_result = connector.execute(connector_request)

    # --- 5. Determine dispatch status ---
    if connector_result.get("status") == "success":
        dispatch_status = "sent"
    else:
        dispatch_status = "failed"

    # --- 6. Redact sensitive fields before storage and response ---
    safe_result = redact_sensitive(connector_result)

    # Build the response result (minimal subset)
    response_result = {
        "status": safe_result.get("status"),
    }
    if "http_status" in safe_result:
        response_result["http_status"] = safe_result["http_status"]
    if "error" in safe_result:
        response_result["error"] = safe_result["error"]

    # --- 7. Write audit record (redacted) ---
    audit = AlertDispatchLog(
        tenant_id=tenant.id,
        alert_status=alert_status,
        alert_count=alert_count,
        dispatch_status=dispatch_status,
        connector="webhook",
        result_json=json.dumps(safe_result, ensure_ascii=False),
    )
    db.add(audit)
    db.commit()

    return AlertDispatchOut(
        status=alert_status,
        alert_count=alert_count,
        dispatch_status=dispatch_status,
        connector="webhook",
        result=response_result,
    )
