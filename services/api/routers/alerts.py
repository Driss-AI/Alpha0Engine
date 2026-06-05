"""
Alerts router (Sprint 10.3) — view alerts + record outcomes.

  GET  /api/v1/alerts/today          — alerts sent today (viewer)
  GET  /api/v1/alerts                 — recent alerts, optional ?lane= / ?bucket= (viewer)
  POST /api/v1/alerts/{id}/outcome    — record my_action + notes (admin)

Forward returns (7/30/90d) and max drawdown are populated by a background helper
(`populate_alert_returns`) that reads DailyPrice — the alert-engine or daily
pipeline calls it; this router exposes the manual outcome fields.
"""
from datetime import date, datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from middleware.auth import require_admin_key, require_api_key
from shared.clients.postgres import get_session
from shared.schemas.alert import Alert
from shared.services.memo import build_memo, render_memo_markdown

router = APIRouter(tags=["Alerts"])

MY_ACTIONS = ["skipped", "watched", "dove", "bought"]


def _alert_outcome(a: Alert) -> Optional[dict[str, Any]]:
    if a.forward_return_7d is None and a.forward_return_30d is None \
            and a.forward_return_90d is None:
        return None
    return {
        "forward_return_7d": a.forward_return_7d,
        "forward_return_30d": a.forward_return_30d,
        "forward_return_90d": a.forward_return_90d,
        "max_drawdown": a.max_drawdown,
    }


def _fallback_memo(a: Alert) -> dict[str, Any]:
    """Build a best-effort memo for an alert recorded before memos were stored."""
    lane_name = "—"
    if a.lane_id:
        try:
            from shared.lanes import get_lane
            lane_name = get_lane(a.lane_id).name
        except Exception:
            lane_name = a.lane_id
    thesis = {
        "lane_id": a.lane_id, "megatrend": "—", "bottleneck": "—",
        "exposure": "—", "why_now": a.why_now or "n/a", "evidence": [],
        "catalyst_type": None, "catalyst_date": None,
    }
    axes = {"opportunity": a.opportunity_score, "risk": a.risk_score,
            "timing": a.timing_score, "confidence": None, "tradability": None}
    return build_memo(
        ticker=a.ticker, company=None, lane_name=lane_name, bucket=a.bucket,
        thesis=thesis, axes=axes, red_flags=[], mechanics={},
    )


class OutcomeUpdate(BaseModel):
    my_action: Optional[str] = None
    outcome_notes: Optional[str] = None
    was_tradable: Optional[bool] = None


def _alert_dict(a: Alert) -> dict[str, Any]:
    return {
        "id": a.id, "ticker": a.ticker, "lane_id": a.lane_id, "bucket": a.bucket,
        "composite_score": a.composite_score,
        "opportunity_score": a.opportunity_score, "risk_score": a.risk_score,
        "timing_score": a.timing_score, "why_now": a.why_now,
        "delivered": a.delivered, "sent_at": a.sent_at,
        "forward_return_7d": a.forward_return_7d,
        "forward_return_30d": a.forward_return_30d,
        "forward_return_90d": a.forward_return_90d,
        "max_drawdown": a.max_drawdown, "was_tradable": a.was_tradable,
        "my_action": a.my_action, "outcome_notes": a.outcome_notes,
    }


@router.get("/alerts/today", dependencies=[Depends(require_api_key)])
async def alerts_today(session: AsyncSession = Depends(get_session)):
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    rows = (await session.exec(
        select(Alert).where(Alert.sent_at >= start).order_by(Alert.opportunity_score.desc())
    )).all()
    return {"date": date.today().isoformat(), "count": len(rows),
            "alerts": [_alert_dict(a) for a in rows]}


@router.get("/alerts", dependencies=[Depends(require_api_key)])
async def list_alerts(
    lane: Optional[str] = None,
    bucket: Optional[str] = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
):
    q = select(Alert).order_by(Alert.sent_at.desc()).limit(min(limit, 500))
    if lane:
        q = q.where(Alert.lane_id == lane)
    if bucket:
        q = q.where(Alert.bucket == bucket)
    rows = (await session.exec(q)).all()
    return {"count": len(rows), "alerts": [_alert_dict(a) for a in rows]}


@router.get("/alerts/{alert_id}/memo", dependencies=[Depends(require_api_key)])
async def alert_memo(alert_id: str, session: AsyncSession = Depends(get_session)):
    """One-page memo for an alert (S13). Returns the memo stored at alert time
    (faithful point-in-time artifact), falling back to a best-effort build for
    older alerts. The realized outcome is always overlaid from the live row."""
    alert = (await session.exec(select(Alert).where(Alert.id == alert_id))).first()
    if not alert:
        raise HTTPException(404, f"alert {alert_id} not found")

    memo = (alert.payload or {}).get("memo") or _fallback_memo(alert)
    outcome = _alert_outcome(alert)
    if outcome:
        memo["outcome"] = outcome
    return {"alert_id": alert.id, "memo": memo, "rendered": render_memo_markdown(memo)}


@router.post("/alerts/{alert_id}/outcome")
async def record_outcome(
    alert_id: str,
    body: OutcomeUpdate,
    session: AsyncSession = Depends(get_session),
    _key: str = Depends(require_admin_key),
):
    if body.my_action is not None and body.my_action not in MY_ACTIONS:
        raise HTTPException(400, f"my_action must be one of {MY_ACTIONS}")

    alert = (await session.exec(select(Alert).where(Alert.id == alert_id))).first()
    if not alert:
        raise HTTPException(404, f"alert {alert_id} not found")

    if body.my_action is not None:
        alert.my_action = body.my_action
    if body.outcome_notes is not None:
        alert.outcome_notes = body.outcome_notes
    if body.was_tradable is not None:
        alert.was_tradable = body.was_tradable
    session.add(alert)
    await session.commit()
    return _alert_dict(alert)
