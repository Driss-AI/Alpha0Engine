"""
1000x Screener Router — Module 5 API endpoints
Conviction-tier screener, watchlist, and per-ticker deep dive.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.equity_screen import EquityScreen, EquityScreenRead
from shared.schemas.entities import Entity
from shared.clients.postgres import get_session

router = APIRouter(tags=["1000x Screener"])


@router.get("/1000x", response_model=List[EquityScreenRead])
async def list_1000x_screens(
    tier: Optional[str] = Query(None, description="Filter: CONVICTION/HIGH/WATCH/SPECULATIVE/PASS"),
    min_score: float = Query(0.0, description="Minimum composite score"),
    min_lenses: int = Query(0, description="Minimum active lenses (0-5)"),
    lens: Optional[str] = Query(None, description="Filter by top lens name"),
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_session),
):
    """List all 1000x screened stocks, sorted by composite score."""
    query = select(EquityScreen).where(EquityScreen.composite_score >= min_score)
    if tier:
        query = query.where(EquityScreen.conviction_tier == tier.upper())
    if min_lenses > 0:
        query = query.where(EquityScreen.active_lenses >= min_lenses)
    if lens:
        query = query.where(EquityScreen.top_lens == lens)
    query = query.order_by(col(EquityScreen.composite_score).desc()).limit(limit)
    return (await session.exec(query)).all()


@router.get("/1000x/watchlist")
async def get_watchlist(
    limit: int = Query(30, le=100),
    session: AsyncSession = Depends(get_session),
):
    """Active watchlist — CONVICTION and HIGH tier stocks."""
    query = select(EquityScreen).where(
        EquityScreen.on_watchlist == True
    ).order_by(col(EquityScreen.composite_score).desc()).limit(limit)

    rows = (await session.exec(query)).all()
    return [
        {
            "ticker": r.ticker,
            "company_name": r.company_name,
            "composite_score": r.composite_score,
            "conviction_tier": r.conviction_tier,
            "active_lenses": r.active_lenses,
            "top_lens": r.top_lens,
            "market_cap_usd": r.market_cap_usd,
            # Lens scores
            "catalyst_score": r.catalyst_score,
            "earnings_score": r.earnings_score,
            "demand_score": r.demand_score,
            "float_score": r.float_score,
            "smart_money_score": r.smart_money_score,
            # Key fields
            "catalyst_type": r.catalyst_type,
            "eps_trajectory": r.eps_trajectory,
            "megatrend_alignment": r.megatrend_alignment,
            "float_category": r.float_category,
            "squeeze_potential": r.squeeze_potential,
            "screening_notes": r.screening_notes,
            "screened_at": r.screened_at.isoformat() if r.screened_at else None,
        }
        for r in rows
    ]


@router.get("/1000x/summary")
async def screener_summary(session: AsyncSession = Depends(get_session)):
    """Summary stats for the 1000x screener dashboard card."""
    all_screens = (await session.exec(select(EquityScreen).limit(5000))).all()
    total = len(all_screens)

    tier_counts = {"CONVICTION": 0, "HIGH": 0, "WATCH": 0, "SPECULATIVE": 0, "PASS": 0}
    avg_score = 0.0
    lens_distribution = {"Binary Catalyst": 0, "Earnings Inflection": 0,
                         "Demand Rider": 0, "Float Mechanics": 0, "Smart Money": 0}
    watchlist_count = 0

    for s in all_screens:
        tier_counts[s.conviction_tier] = tier_counts.get(s.conviction_tier, 0) + 1
        avg_score += s.composite_score
        if s.top_lens:
            lens_distribution[s.top_lens] = lens_distribution.get(s.top_lens, 0) + 1
        if s.on_watchlist:
            watchlist_count += 1

    if total > 0:
        avg_score = round(avg_score / total, 4)

    # Top 5 highest conviction
    top_picks = sorted(all_screens, key=lambda x: x.composite_score, reverse=True)[:5]

    return {
        "total_screened": total,
        "watchlist_count": watchlist_count,
        "avg_composite_score": avg_score,
        "tier_breakdown": tier_counts,
        "lens_distribution": lens_distribution,
        "top_picks": [
            {
                "ticker": s.ticker,
                "company_name": s.company_name,
                "composite_score": s.composite_score,
                "conviction_tier": s.conviction_tier,
                "active_lenses": s.active_lenses,
                "top_lens": s.top_lens,
                "screening_notes": s.screening_notes,
            }
            for s in top_picks
        ],
    }


@router.get("/1000x/{ticker}")
async def get_ticker_deep_dive(
    ticker: str,
    session: AsyncSession = Depends(get_session),
):
    """Deep dive for a specific ticker — full lens breakdown."""
    upper = ticker.upper()

    # Strategy 1: Find entity by ticker, then get its equity screen
    entity_result = await session.exec(
        select(Entity).where(Entity.ticker == upper)
    )
    entity = entity_result.first()
    screen = None

    if entity:
        result = await session.exec(
            select(EquityScreen).where(EquityScreen.entity_id == entity.id)
        )
        screen = result.first()
        # Ensure the screen has the correct ticker/name from the entity
        if screen:
            screen.ticker = entity.ticker
            screen.company_name = entity.name

    # Strategy 2: Direct ticker match in equity_screens
    if not screen:
        result = await session.exec(
            select(EquityScreen).where(EquityScreen.ticker == upper)
        )
        screen = result.first()

    # Strategy 3: Try by entity_id
    if not screen:
        result = await session.exec(
            select(EquityScreen).where(EquityScreen.entity_id == ticker)
        )
        screen = result.first()

    if not screen:
        raise HTTPException(status_code=404, detail=f"No 1000x screen found for {ticker}")

    return {
        "ticker": screen.ticker,
        "company_name": screen.company_name,
        "cik": screen.cik,
        "entity_id": screen.entity_id,
        "composite_score": screen.composite_score,
        "conviction_tier": screen.conviction_tier,
        "active_lenses": screen.active_lenses,
        "top_lens": screen.top_lens,
        "screening_notes": screen.screening_notes,
        "on_watchlist": screen.on_watchlist,
        "market_cap_usd": screen.market_cap_usd,
        # ── Lens 1: Binary Catalyst ────────────────────
        "lens_1_binary_catalyst": {
            "score": screen.catalyst_score,
            "type": screen.catalyst_type,
            "proximity_days": screen.catalyst_proximity_days,
            "details": screen.catalyst_details,
        },
        # ── Lens 2: Earnings Inflection ────────────────
        "lens_2_earnings_inflection": {
            "score": screen.earnings_score,
            "trajectory": screen.eps_trajectory,
            "quarters_to_profit": screen.quarters_to_profit,
            "revenue_acceleration": screen.revenue_acceleration,
            "margin_expansion_rate": screen.margin_expansion_rate,
            "details": screen.earnings_details,
        },
        # ── Lens 3: Demand Rider ───────────────────────
        "lens_3_demand_rider": {
            "score": screen.demand_score,
            "megatrend": screen.megatrend_alignment,
            "theme_strength": screen.theme_strength,
            "institutional_neglect": screen.institutional_neglect,
            "details": screen.demand_details,
        },
        # ── Lens 4: Float Mechanics ────────────────────
        "lens_4_float_mechanics": {
            "score": screen.float_score,
            "float_category": screen.float_category,
            "float_shares": screen.float_shares,
            "short_interest": screen.short_interest,
            "short_pct_float": screen.short_pct_float,
            "squeeze_potential": screen.squeeze_potential,
            "days_to_cover": screen.days_to_cover,
            "details": screen.float_details,
        },
        # ── Lens 5: Smart Money ────────────────────────
        "lens_5_smart_money": {
            "score": screen.smart_money_score,
            "institutional_buys": screen.institutional_buys_13f,
            "insider_buys": screen.insider_buys_form4,
            "insider_buy_value": screen.insider_buy_value_usd,
            "details": screen.smart_money_details,
        },
        # ── Meta ───────────────────────────────────────
        "shares_outstanding": screen.shares_outstanding,
        "screened_at": screen.screened_at.isoformat() if screen.screened_at else None,
        "updated_at": screen.updated_at.isoformat() if screen.updated_at else None,
    }
