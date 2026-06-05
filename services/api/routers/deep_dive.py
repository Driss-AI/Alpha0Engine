from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.clients.postgres import get_session
from shared.schemas.entities import Entity
from shared.schemas.equity_screen import EquityScreen
from shared.schemas.signals import Signal, SignalRead
from shared.schemas.ticker_timeline import TickerTimeline, TickerTimelineRead
from shared.schemas.candidate_lane import CandidateLane
from shared.schemas.evidence_item import EvidenceItem
from shared.schemas.catalyst_event import CatalystEvent
from shared.scoring import build_thesis
from shared.services.memo import build_memo

router = APIRouter(tags=["Deep Dive"])


async def _get_entity_by_ticker(ticker: str, session: AsyncSession) -> Optional[Entity]:
    result = await session.exec(select(Entity).where(Entity.ticker == ticker.upper()))
    return result.first()


@router.get("/1000x/{ticker}/timeline", response_model=List[TickerTimelineRead])
async def get_ticker_timeline(
    ticker: str,
    event_type: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    session: AsyncSession = Depends(get_session),
):
    query = select(TickerTimeline).where(TickerTimeline.ticker == ticker.upper())
    if event_type:
        query = query.where(TickerTimeline.event_type == event_type)

    result = await session.exec(query.order_by(TickerTimeline.event_date.desc()).limit(limit))
    return result.all()


@router.get("/1000x/{ticker}/signals", response_model=List[SignalRead])
async def get_ticker_signals(
    ticker: str,
    signal_type: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    session: AsyncSession = Depends(get_session),
):
    entity = await _get_entity_by_ticker(ticker, session)
    if not entity:
        raise HTTPException(404, f"No entity found for ticker {ticker.upper()}")

    query = select(Signal).where(Signal.entity_id == entity.id)
    if signal_type:
        query = query.where(Signal.signal_type == signal_type)

    result = await session.exec(query.order_by(Signal.signal_date.desc()).limit(limit))
    return result.all()


@router.get("/1000x/{ticker}/filings")
async def get_ticker_filings(
    ticker: str,
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    entity = await _get_entity_by_ticker(ticker, session)
    if not entity:
        raise HTTPException(404, f"No entity found for ticker {ticker.upper()}")

    result = await session.exec(
        select(Signal)
        .where(Signal.entity_id == entity.id)
        .where(Signal.source.in_(["edgar", "edgar_8k", "edgar_form4", "sec_13f"]))
        .order_by(Signal.signal_date.desc())
        .limit(50)
    )

    filings = []
    for signal in result.all():
        raw = signal.raw_data or {}
        filings.append(
            {
                "signal_id": signal.id,
                "type": signal.signal_type,
                "date": signal.signal_date,
                "source": signal.source,
                "source_id": signal.source_id,
                "url": raw.get("url") or raw.get("filing_url") or raw.get("accession_url"),
                "title": raw.get("title") or raw.get("form") or signal.notes,
                "raw_data": raw,
            }
        )

    return {
        "ticker": ticker.upper(),
        "entity_id": entity.id,
        "cik": entity.cik,
        "filings": filings,
    }


@router.get("/1000x/{ticker}/eps-chart")
async def get_ticker_eps_chart(
    ticker: str,
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    result = await session.exec(select(EquityScreen).where(EquityScreen.ticker == ticker.upper()))
    screen = result.first()
    if not screen:
        raise HTTPException(404, f"No equity screen found for ticker {ticker.upper()}")

    earnings = screen.earnings_details or {}
    return {
        "ticker": ticker.upper(),
        "entity_id": screen.entity_id,
        "eps_trajectory": screen.eps_trajectory,
        "quarters_to_profit": screen.quarters_to_profit,
        "revenue_acceleration": screen.revenue_acceleration,
        "margin_expansion_rate": screen.margin_expansion_rate,
        "earnings_details": earnings,
    }


@router.get("/1000x/{ticker}/research")
async def get_ticker_research_page(
    ticker: str,
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    symbol = ticker.upper()

    entity_result = await session.exec(select(Entity).where(Entity.ticker == symbol))
    entity = entity_result.first()

    screen_result = await session.exec(select(EquityScreen).where(EquityScreen.ticker == symbol))
    screen = screen_result.first()

    timeline_result = await session.exec(
        select(TickerTimeline)
        .where(TickerTimeline.ticker == symbol)
        .order_by(TickerTimeline.event_date.desc())
        .limit(50)
    )

    if not entity and not screen:
        raise HTTPException(404, f"No research data found for ticker {symbol}")

    # ── Sprint 9.7: lane context + 5-axis scores + evidence + red flags ──────
    lanes_ctx: List[Dict[str, Any]] = []
    if entity:
        lane_rows = (await session.exec(
            select(CandidateLane).where(CandidateLane.entity_id == entity.id)
        )).all()
        try:
            from shared.lanes import get_lane
            for lr in lane_rows:
                try:
                    lane = get_lane(lr.lane_id)
                    lanes_ctx.append({
                        "lane_id": lr.lane_id,
                        "name": lane.name,
                        "megatrend": lane.megatrend,
                        "lane_score": lr.lane_score,
                        "bottleneck_exposure": lr.bottleneck_exposure,
                    })
                except KeyError:
                    continue
        except Exception:
            pass

    evidence_rows = []
    if entity:
        evs = (await session.exec(
            select(EvidenceItem).where(EvidenceItem.entity_id == entity.id).limit(25)
        )).all()
        evidence_rows = [
            {"source": e.source, "source_url": e.source_url, "summary": e.summary,
             "lane_id": e.lane_id, "lens": e.lens, "captured_at": e.captured_at}
            for e in evs
        ]

    axis_scores = None
    red_flags = None
    bucket = None
    if screen:
        axis_scores = {
            "opportunity": screen.opportunity_score,
            "risk": screen.risk_score,
            "timing": screen.timing_score,
            "confidence": screen.confidence_score,
            "tradability": screen.tradability_score,
        }
        bucket = screen.bucket
        raw = screen.raw_data or {}
        red_flags = raw.get("red_flags", [])

    lens_scorecard = None
    if screen:
        lens_scorecard = {
            "composite_score": screen.composite_score,
            "conviction_tier": screen.conviction_tier,
            "active_lenses": screen.active_lenses,
            "top_lens": screen.top_lens,
            "lenses": {
                "catalyst": {
                    "score": screen.catalyst_score,
                    "type": screen.catalyst_type,
                    "details": screen.catalyst_details,
                },
                "earnings": {
                    "score": screen.earnings_score,
                    "trajectory": screen.eps_trajectory,
                    "details": screen.earnings_details,
                },
                "demand": {
                    "score": screen.demand_score,
                    "megatrend": screen.megatrend_alignment,
                    "details": screen.demand_details,
                },
                "float": {
                    "score": screen.float_score,
                    "category": screen.float_category,
                    "details": screen.float_details,
                },
                "smart_money": {
                    "score": screen.smart_money_score,
                    "details": screen.smart_money_details,
                },
            },
        }

    # ── Sprint 13: one-page memo for this live candidate ─────────────────────
    memo = None
    if screen and screen.best_lane_id:
        try:
            from shared.lanes import get_lane
            try:
                lane_name = get_lane(screen.best_lane_id).name
            except KeyError:
                lane_name = screen.best_lane_id

            best_bottlenecks: List[str] = []
            for lc in lanes_ctx:
                if lc["lane_id"] == screen.best_lane_id:
                    best_bottlenecks = lc.get("bottleneck_exposure") or []
                    break

            today = datetime.now(timezone.utc).date()
            cat_rows = (await session.exec(
                select(CatalystEvent).where(
                    CatalystEvent.ticker == symbol,
                    CatalystEvent.status == "upcoming",
                ).order_by(CatalystEvent.expected_date)
            )).all()
            nearest = None
            for r in cat_rows:
                if r.expected_date and r.expected_date >= today:
                    nearest = {"catalyst_type": r.catalyst_type,
                               "expected_date": r.expected_date, "title": r.title}
                    break

            thesis = build_thesis(
                ticker=symbol, company=screen.company_name,
                lane_id=screen.best_lane_id, bottlenecks=best_bottlenecks,
                evidence=[{"summary": e["summary"], "source_url": e["source_url"],
                           "source": e["source"]} for e in evidence_rows],
                nearest_catalyst=nearest,
                short_pct_float=screen.short_pct_float,
            ).to_dict()
            memo = build_memo(
                ticker=symbol, company=screen.company_name, lane_name=lane_name,
                bucket=bucket or "WATCH", thesis=thesis, axes=axis_scores or {},
                red_flags=red_flags or [],
                mechanics={"float": screen.float_shares,
                           "short_pct_float": screen.short_pct_float},
            )
        except Exception:
            memo = None

    return {
        "ticker": symbol,
        "entity": entity.model_dump() if entity else None,
        "screen": screen.model_dump() if screen else None,
        "lens_scorecard": lens_scorecard,
        # Sprint 9.7 lane-aware deep dive
        "bucket": bucket,
        "axis_scores": axis_scores,
        "red_flags": red_flags,
        "lanes": lanes_ctx,
        "evidence": evidence_rows,
        # Sprint 13 one-page memo
        "memo": memo,
        "timeline": [item.model_dump() for item in timeline_result.all()],
        "generated_at": datetime.now(timezone.utc),
    }
