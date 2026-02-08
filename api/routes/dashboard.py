"""
GET /v1/dashboard -- Governance metrics.

Returns aggregated trust scores, flag trends, and compliance metrics.
In production, this would query the audit store and compute real stats.

For the demo, it returns realistic simulated data that changes slightly
on each call (using random variance) so the dashboard looks alive.
"""

import random
from typing import Literal

from fastapi import APIRouter, Query

from api.models.schemas import DashboardMetrics, FlagCount
from api.store import audit_records

router = APIRouter()

# ---------------------------------------------------------------------------
# Baseline metrics for each period length.
# These give the dashboard realistic-looking numbers. Random variance is
# applied on each call so refreshing the page shows slight changes.
# ---------------------------------------------------------------------------

PERIOD_BASELINES = {
    "7d": {
        "label_days": 7,
        "total": 1247,
        "avg_score": 84.3,
        "approved_pct": 0.873,
        "flagged_pct": 0.114,
        "blocked_pct": 0.013,
        "injections": 3,
    },
    "30d": {
        "label_days": 30,
        "total": 5420,
        "avg_score": 82.1,
        "approved_pct": 0.856,
        "flagged_pct": 0.124,
        "blocked_pct": 0.020,
        "injections": 11,
    },
    "90d": {
        "label_days": 90,
        "total": 14830,
        "avg_score": 80.7,
        "approved_pct": 0.841,
        "flagged_pct": 0.132,
        "blocked_pct": 0.027,
        "injections": 28,
    },
}


def _vary(value: int | float, pct: float = 0.05) -> int | float:
    """Add random variance to a number (default +/- 5%).
    Makes the dashboard look dynamic on refresh."""
    delta = value * random.uniform(-pct, pct)
    if isinstance(value, int):
        return max(0, int(value + delta))
    return round(value + delta, 1)


@router.get(
    "/v1/dashboard",
    response_model=DashboardMetrics,
    summary="Get governance metrics",
    description=(
        "Returns aggregated governance metrics for the dashboard. "
        "Pass a period parameter (7d, 30d, 90d) to control the time range."
    ),
    tags=["Monitoring"],
)
async def dashboard(
    period: Literal["7d", "30d", "90d"] = Query(
        default="7d",
        description="Time period for the metrics report.",
    ),
) -> DashboardMetrics:
    baseline = PERIOD_BASELINES[period]

    # If we have real audit records from /v1/verify calls, mix them in
    real_count = len(audit_records)

    total = _vary(baseline["total"]) + real_count
    avg_score = _vary(baseline["avg_score"])
    approved = int(total * baseline["approved_pct"])
    flagged = int(total * baseline["flagged_pct"])
    blocked = total - approved - flagged

    # Build the period label
    from datetime import datetime, timedelta, timezone
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=baseline["label_days"])
    period_label = f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}"

    # Simulated top flags -- these are the most common governance issues
    top_flags = [
        FlagCount(type="semantic_entropy", count=_vary(89)),
        FlagCount(type="unverified_claim", count=_vary(47)),
        FlagCount(type="weak_entailment", count=_vary(23)),
        FlagCount(type="mild_preference", count=_vary(12)),
        FlagCount(type="entailment_contradiction", count=_vary(8)),
        FlagCount(type="strong_bias", count=_vary(3)),
    ]

    compliance = round(approved / max(total, 1) * 100, 1)

    # Trend: if avg score is above 83, improving; below 78, declining
    if avg_score > 83:
        trend = "improving"
    elif avg_score < 78:
        trend = "declining"
    else:
        trend = "stable"

    return DashboardMetrics(
        period=period_label,
        total_verifications=total,
        avg_trust_score=avg_score,
        auto_approved=approved,
        flagged_for_review=flagged,
        auto_blocked=blocked,
        injection_attempts_blocked=_vary(baseline["injections"]),
        top_flags=top_flags,
        compliance_score=compliance,
        trend=trend,
    )
