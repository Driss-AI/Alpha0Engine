"""
Lens 4 — Float Mechanics
==========================
Low float + high short interest = squeeze amplification potential.
When a catalyst fires on a low-float stock with high short interest,
the forced covering amplifies the move 10-100x beyond fair value.

Data sources:
  - SEC EDGAR (shares outstanding, insider holdings for float calc)
  - FINRA short interest reports (published bi-monthly)
  - Entity/signal tables for supplemental data
"""
import os
import logging
import httpx
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

SEC_BASE = "https://data.sec.gov"
EDGAR_UA = os.environ.get("EDGAR_USER_AGENT", "Alpha0Engine contact@alpha0engine.com")
HEADERS = {"User-Agent": EDGAR_UA, "Accept": "application/json"}


# ── Float Categories ────────────────────────────────────────
def _categorize_float(float_shares: Optional[float]) -> str:
    """Classify float size."""
    if float_shares is None:
        return "unknown"
    if float_shares < 5_000_000:
        return "nano"       # <5M shares: extreme squeeze potential
    if float_shares < 15_000_000:
        return "micro"      # 5-15M: very tight
    if float_shares < 50_000_000:
        return "small"      # 15-50M: still exploitable
    if float_shares < 200_000_000:
        return "normal"     # 50-200M: moderate
    return "large"          # >200M: hard to squeeze


def _score_float_size(float_shares: Optional[float]) -> float:
    """Lower float = higher squeeze amplification."""
    if float_shares is None:
        return 0.0
    if float_shares < 2_000_000:
        return 1.0
    if float_shares < 5_000_000:
        return 0.90
    if float_shares < 10_000_000:
        return 0.75
    if float_shares < 20_000_000:
        return 0.60
    if float_shares < 50_000_000:
        return 0.40
    if float_shares < 100_000_000:
        return 0.20
    return 0.05


def _score_short_interest(short_pct_float: Optional[float]) -> float:
    """Higher short interest = more forced buying on squeeze."""
    if short_pct_float is None:
        return 0.0
    if short_pct_float > 0.40:
        return 1.0     # >40% short: extreme squeeze
    if short_pct_float > 0.25:
        return 0.90
    if short_pct_float > 0.15:
        return 0.75
    if short_pct_float > 0.10:
        return 0.55
    if short_pct_float > 0.05:
        return 0.30
    return 0.10


def _score_days_to_cover(dtc: Optional[float]) -> float:
    """Days to cover = short interest / avg daily volume. Higher = harder to exit."""
    if dtc is None:
        return 0.0
    if dtc > 10:
        return 1.0     # >10 days: shorts are trapped
    if dtc > 7:
        return 0.85
    if dtc > 5:
        return 0.65
    if dtc > 3:
        return 0.45
    if dtc > 1:
        return 0.20
    return 0.05


def _compute_squeeze_potential(
    float_score: float,
    short_score: float,
    dtc_score: float,
) -> float:
    """
    Squeeze potential = float tightness × short exposure × exit difficulty.
    All three must be elevated for a real squeeze.
    """
    # Geometric-ish mean to require all dimensions
    if float_score == 0 or short_score == 0:
        return 0.0
    raw = (float_score * 0.35 + short_score * 0.40 + dtc_score * 0.25)
    # Bonus: if all three are >0.5, multiplicative boost
    if float_score > 0.5 and short_score > 0.5 and dtc_score > 0.5:
        raw = min(raw * 1.2, 1.0)
    return round(raw, 4)


async def fetch_shares_outstanding(cik: str) -> Optional[float]:
    """Get shares outstanding from SEC EDGAR XBRL."""
    cik_padded = cik.zfill(10)
    url = f"{SEC_BASE}/api/xbrl/companyfacts/CIK{cik_padded}.json"

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code != 200:
                return None
            facts = resp.json()

            # Try DEI first (most reliable for shares outstanding)
            for concept in [
                "EntityCommonStockSharesOutstanding",
                "CommonStockSharesOutstanding",
            ]:
                try:
                    units = facts["facts"]["dei"][concept]["units"]
                    values = units.get("shares", next(iter(units.values()), []))
                    if values:
                        values.sort(key=lambda x: x.get("end", ""), reverse=True)
                        return float(values[0]["val"])
                except (KeyError, TypeError):
                    pass

            # Fallback: us-gaap
            for concept in [
                "CommonStockSharesOutstanding",
                "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
            ]:
                try:
                    units = facts["facts"]["us-gaap"][concept]["units"]
                    values = units.get("shares", next(iter(units.values()), []))
                    if values:
                        values.sort(key=lambda x: x.get("end", ""), reverse=True)
                        return float(values[0]["val"])
                except (KeyError, TypeError):
                    pass

            return None
        except Exception as e:
            logger.error(f"Shares outstanding fetch failed for CIK {cik}: {e}")
            return None


async def fetch_finra_short_interest(ticker: str) -> Optional[Dict[str, Any]]:
    """
    Fetch short interest data from FINRA.
    FINRA publishes short interest bi-monthly (free, delayed data).
    Falls back to SEC short interest filings if FINRA is unavailable.
    """
    # FINRA's public short interest data
    # Note: FINRA's direct API requires registration.
    # We use the SEC's short interest compilation as fallback.
    try:
        # This is a paginated UI — for production, use FINRA API with key.
        # For now, return None and rely on SEC/signal data.
        logger.debug(f"FINRA short interest lookup for {ticker} — using signal fallback")
        return None
    except Exception as e:
        logger.warning(f"FINRA lookup failed for {ticker}: {e}")
        return None


def estimate_float_from_signals(
    shares_outstanding: Optional[float],
    signals: list,
) -> Optional[float]:
    """
    Estimate float from available data.
    Float ≈ shares outstanding - insider holdings - institutional locked shares.
    """
    if shares_outstanding is None:
        return None

    # Estimate insider holdings from Form 4 signals
    insider_shares = 0
    for sig in signals:
        if sig.get("signal_type") == "form_4_insider":
            raw = sig.get("raw_data") or {}
            insider_shares += raw.get("shares_held", 0)

    # If no insider data, estimate ~25% insider ownership for micro-caps
    if insider_shares == 0:
        estimated_insider_pct = 0.25
        insider_shares = shares_outstanding * estimated_insider_pct

    float_shares = max(shares_outstanding - insider_shares, 0)
    return float_shares


def estimate_short_from_signals(signals: list) -> tuple:
    """Extract short interest data from signal records if available."""
    short_interest = None
    for sig in signals:
        raw = sig.get("raw_data") or {}
        if "short_interest" in raw:
            short_interest = raw["short_interest"]
        if "short_pct_float" in raw:
            return raw.get("short_interest"), raw["short_pct_float"]
    return short_interest, None


async def score_float_mechanics(
    ticker: Optional[str],
    cik: Optional[str],
    signals: list,
    shares_outstanding: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Compute Lens 4 score for float mechanics / squeeze potential.

    Returns:
        float_score (0.0-1.0)
        float_category
        squeeze_potential
        days_to_cover
        float_details
    """
    # Get shares outstanding
    if shares_outstanding is None and cik:
        shares_outstanding = await fetch_shares_outstanding(cik)

    # Estimate float
    float_shares = estimate_float_from_signals(shares_outstanding, signals)

    # Get short interest
    short_interest, short_pct = estimate_short_from_signals(signals)
    if ticker and short_interest is None:
        finra_data = await fetch_finra_short_interest(ticker)
        if finra_data:
            short_interest = finra_data.get("short_interest")
            short_pct = finra_data.get("short_pct_float")

    # Compute short_pct_float if we have both
    if short_pct is None and short_interest and float_shares and float_shares > 0:
        short_pct = short_interest / float_shares

    # Estimate days to cover (need volume data — use signal frequency as proxy)
    days_to_cover = None
    if short_interest and float_shares:
        # Rough estimate: avg daily volume ≈ 1-3% of float for micro-caps
        estimated_daily_vol = float_shares * 0.015
        if estimated_daily_vol > 0:
            days_to_cover = round(short_interest / estimated_daily_vol, 1)

    # Score components
    float_s = _score_float_size(float_shares)
    short_s = _score_short_interest(short_pct)
    dtc_s = _score_days_to_cover(days_to_cover)

    squeeze = _compute_squeeze_potential(float_s, short_s, dtc_s)
    category = _categorize_float(float_shares)

    # Composite: 40% float tightness, 35% short exposure, 25% squeeze potential
    composite = 0.40 * float_s + 0.35 * short_s + 0.25 * squeeze
    composite = round(min(max(composite, 0.0), 1.0), 4)

    cited_ids = [s.get("signal_id") for s in signals if s.get("signal_id")]

    return {
        "float_score": composite,
        "float_category": category,
        "squeeze_potential": squeeze,
        "days_to_cover": days_to_cover,
        "float_shares": float_shares,
        "short_interest": short_interest,
        "short_pct_float": short_pct,
        "cited_signal_ids": cited_ids,
        "float_details": {
            "components": {
                "float_tightness": float_s,
                "short_exposure": short_s,
                "days_to_cover_score": dtc_s,
                "squeeze_potential": squeeze,
            },
            "shares_outstanding": shares_outstanding,
            "float_shares": float_shares,
            "float_category": category,
            "cited_signal_ids": cited_ids,
        },
    }
