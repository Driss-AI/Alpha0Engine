"""
Private Company Proxy Screener
==============================
Since private companies don't file 10-Qs, we estimate fundamentals
from proxy signals: Form D filings, secondary market trades,
funding rounds, and talent signals.
"""
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def estimate_total_raised(signals: List[Dict[str, Any]]) -> Optional[float]:
    """
    Estimate total capital raised from Form D filings.
    Form D totalOfferingAmount = cumulative raise for that offering.
    We take the max across filings (filings amend, not stack).
    """
    form_d_signals = [s for s in signals if s.get("signal_type") == "form_d"]
    if not form_d_signals:
        return None

    max_offering = 0.0
    for s in form_d_signals:
        raw = s.get("raw_data", {})
        if isinstance(raw, dict):
            amount = raw.get("totalOfferingAmount") or raw.get("offering_amount") or 0
            try:
                max_offering = max(max_offering, float(amount))
            except (ValueError, TypeError):
                pass

    return max_offering if max_offering > 0 else None


def estimate_last_round_valuation(signals: List[Dict[str, Any]]) -> Optional[float]:
    """
    Estimate last-round valuation from Form D data.
    Logic: If Form D shows $50M raise and raw_data mentions 10% dilution → ~$500M.
    Fallback: 3-5x total raised as rough proxy.
    """
    form_d_signals = sorted(
        [s for s in signals if s.get("signal_type") == "form_d"],
        key=lambda s: s.get("signal_date", ""),
        reverse=True,
    )
    if not form_d_signals:
        return None

    latest = form_d_signals[0]
    raw = latest.get("raw_data", {})
    if isinstance(raw, dict):
        # Check if valuation is directly stated
        val = raw.get("pre_money_valuation") or raw.get("valuation")
        if val:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass

        # Estimate from offering amount (4x multiplier = ~25% dilution assumption)
        amount = raw.get("totalOfferingAmount") or raw.get("offering_amount")
        if amount:
            try:
                return float(amount) * 4.0
            except (ValueError, TypeError):
                pass

    # Fallback: total raised * 4x
    total = estimate_total_raised(signals)
    if total:
        return total * 4.0
    return None


def estimate_secondary_premium_discount(signals: List[Dict[str, Any]]) -> Optional[float]:
    """
    Calculate secondary market price vs last-round valuation.
    Returns % premium(+) or discount(-).
    secondary_vs_primary = (secondary_price / primary_price - 1) * 100
    """
    secondary_signals = sorted(
        [s for s in signals if s.get("signal_type") == "secondary_trade"],
        key=lambda s: s.get("signal_date", ""),
        reverse=True,
    )
    if not secondary_signals:
        return None

    latest = secondary_signals[0]
    raw = latest.get("raw_data", {})
    if isinstance(raw, dict):
        sec_price = raw.get("price_per_share") or raw.get("secondary_price")
        primary_price = raw.get("last_round_pps") or raw.get("primary_price")
        if sec_price and primary_price:
            try:
                return round((float(sec_price) / float(primary_price) - 1) * 100, 2)
            except (ValueError, TypeError, ZeroDivisionError):
                pass

    # Use signal value if available (already normalized by ingest)
    if latest.get("value") and abs(latest["value"]) > 0:
        return round(latest["value"] * 100, 2)

    return None


def estimate_burn_rate(signals: List[Dict[str, Any]]) -> Optional[float]:
    """
    Estimate monthly cash burn from funding cadence.
    If company raised $50M 18 months ago → rough burn = $50M / 24 months
    (assuming 24-month runway at raise time, industry standard).
    """
    form_d_signals = sorted(
        [s for s in signals if s.get("signal_type") == "form_d"],
        key=lambda s: s.get("signal_date", ""),
        reverse=True,
    )
    if not form_d_signals:
        return None

    latest = form_d_signals[0]
    raw = latest.get("raw_data", {})
    if isinstance(raw, dict):
        amount = raw.get("totalOfferingAmount") or raw.get("offering_amount")
        if amount:
            try:
                return round(float(amount) / 24.0, 2)  # 24-month runway assumption
            except (ValueError, TypeError):
                pass
    return None


def estimate_runway(signals: List[Dict[str, Any]]) -> Optional[float]:
    """
    Estimate remaining cash runway in months.
    Uses: total raised, burn rate, time since last funding.
    """
    total_raised = estimate_total_raised(signals)
    burn_rate = estimate_burn_rate(signals)
    if not total_raised or not burn_rate or burn_rate <= 0:
        return None

    # Time elapsed since last funding
    form_d_signals = sorted(
        [s for s in signals if s.get("signal_type") == "form_d"],
        key=lambda s: s.get("signal_date", ""),
        reverse=True,
    )
    if form_d_signals:
        latest_date = form_d_signals[0].get("signal_date")
        if isinstance(latest_date, str):
            try:
                latest_date = datetime.fromisoformat(latest_date.replace("Z", "+00:00"))
            except ValueError:
                latest_date = datetime.utcnow()
        elif not isinstance(latest_date, datetime):
            latest_date = datetime.utcnow()

        months_elapsed = max((datetime.utcnow() - latest_date.replace(tzinfo=None)).days / 30, 0)
        cash_remaining = total_raised - (burn_rate * months_elapsed)
        if cash_remaining > 0:
            return round(cash_remaining / burn_rate, 1)

    return None


def screen_private_company(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Full private-company proxy screen from available signals.
    """
    return {
        "total_raised": estimate_total_raised(signals),
        "last_round_valuation": estimate_last_round_valuation(signals),
        "secondary_vs_primary": estimate_secondary_premium_discount(signals),
        "estimated_burn_rate": estimate_burn_rate(signals),
        "estimated_runway_months": estimate_runway(signals),
        "form_d_count": len([s for s in signals if s.get("signal_type") == "form_d"]),
        "secondary_trade_count": len([s for s in signals if s.get("signal_type") == "secondary_trade"]),
        "screened_at": datetime.utcnow().isoformat(),
    }
