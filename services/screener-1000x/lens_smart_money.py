"""
Lens 5 — Smart Money Accumulation
===================================
Detects institutional (13F) and insider (Form 4) buying patterns
that precede major catalysts. When smart money quietly accumulates
before a binary event, it's the strongest confirmation signal.

Key patterns:
  - New 13F positions in micro-caps (institutions entering)
  - Cluster insider buys (multiple insiders buying in same window)
  - Size of buys relative to market cap
  - Timing: buys accelerating toward known catalyst dates

Data sources:
  - Existing 13F ingestion (ingest-13f service)
  - SEC EDGAR Form 4 (insider transactions)
  - Signals table (sec_13f, form_4 signal types)
"""
import os
import logging
import httpx
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

SEC_BASE = "https://data.sec.gov"
EDGAR_UA = os.environ.get("EDGAR_USER_AGENT", "Alpha0Engine contact@alpha0engine.com")
HEADERS = {"User-Agent": EDGAR_UA, "Accept": "application/json"}


def _score_institutional_buying(
    signals_13f: List[Dict[str, Any]],
    market_cap: Optional[float],
) -> Dict[str, Any]:
    """
    Score institutional 13F buying activity.
    New positions in micro-caps from quality institutions = strongest signal.
    """
    if not signals_13f:
        return {"score": 0.0, "buy_count": 0, "details": "no_13f_data"}

    now = datetime.utcnow()
    recent_cutoff = now - timedelta(days=180)  # Look at last 2 quarters

    recent_buys = []
    for sig in signals_13f:
        sig_date = sig.get("signal_date")
        if sig_date:
            try:
                if isinstance(sig_date, str):
                    dt = datetime.fromisoformat(sig_date.replace("Z", "+00:00")).replace(tzinfo=None)
                else:
                    dt = sig_date
                if dt >= recent_cutoff:
                    recent_buys.append(sig)
            except (ValueError, TypeError):
                recent_buys.append(sig)  # Include if date parsing fails
        else:
            recent_buys.append(sig)

    buy_count = len(recent_buys)
    if buy_count == 0:
        return {"score": 0.0, "buy_count": 0, "details": "no_recent_13f"}

    # Score by number of new institutional buyers
    if buy_count >= 10:
        count_score = 1.0
    elif buy_count >= 5:
        count_score = 0.80
    elif buy_count >= 3:
        count_score = 0.60
    elif buy_count >= 2:
        count_score = 0.40
    else:
        count_score = 0.20

    # Market cap factor: institutional buying in micro-caps = more significant
    mcap_factor = 0.5  # Default
    if market_cap is not None:
        mc_m = market_cap / 1e6
        if mc_m < 100:
            mcap_factor = 1.0   # Institutions entering nano-cap = very bullish
        elif mc_m < 500:
            mcap_factor = 0.80
        elif mc_m < 2000:
            mcap_factor = 0.50
        else:
            mcap_factor = 0.20

    # Total value of 13F positions
    total_value = 0
    for sig in recent_buys:
        raw = sig.get("raw_data") or {}
        # ingest-13f writes `holding_value_usd`; older paths used value_usd/value.
        total_value += (raw.get("value_usd", 0) or raw.get("holding_value_usd", 0)
                        or raw.get("value", 0) or 0)

    # Value relative to market cap (if known)
    value_ratio_score = 0.3
    if market_cap and market_cap > 0 and total_value > 0:
        ratio = total_value / market_cap
        if ratio > 0.05:
            value_ratio_score = 1.0
        elif ratio > 0.02:
            value_ratio_score = 0.70
        elif ratio > 0.01:
            value_ratio_score = 0.50
        elif ratio > 0.005:
            value_ratio_score = 0.30

    combined = 0.45 * count_score + 0.30 * mcap_factor + 0.25 * value_ratio_score
    return {
        "score": round(combined, 4),
        "buy_count": buy_count,
        "total_value": total_value,
        "details": f"{buy_count} institutional buyers in last 6 months",
    }


def _score_insider_buying(
    signals_form4: List[Dict[str, Any]],
    market_cap: Optional[float],
) -> Dict[str, Any]:
    """
    Score insider Form 4 buying.
    Cluster insider buys (multiple insiders buying together) = strongest signal.
    Large purchases relative to market cap = high conviction.
    """
    if not signals_form4:
        return {"score": 0.0, "buy_count": 0, "buy_value": 0, "details": "no_form4_data"}

    now = datetime.utcnow()
    recent_cutoff = now - timedelta(days=120)  # Last quarter

    buys = []
    sells = []
    for sig in signals_form4:
        raw = sig.get("raw_data") or {}
        st = sig.get("signal_type")
        tx_type = raw.get("transaction_type", "").lower()
        notes = (sig.get("notes") or "").lower()

        # The signal_type itself encodes direction (S8 code-first form-4); fall
        # back to transaction_type/notes for legacy rows.
        is_buy = (st == "insider_buy_cluster"
                  or "purchase" in tx_type or "buy" in notes or "acquisition" in tx_type)
        is_sell = (st == "insider_sell_cluster"
                   or "sale" in tx_type or "sell" in notes or "disposition" in tx_type)

        sig_date = sig.get("signal_date")
        is_recent = True
        if sig_date:
            try:
                if isinstance(sig_date, str):
                    dt = datetime.fromisoformat(sig_date.replace("Z", "+00:00")).replace(tzinfo=None)
                else:
                    dt = sig_date
                is_recent = dt >= recent_cutoff
            except (ValueError, TypeError):
                pass

        if is_buy and is_recent:
            buys.append({
                "value": raw.get("value_usd", 0) or raw.get("transaction_value", 0) or 0,
                "shares": raw.get("shares", 0) or 0,
                "insider": raw.get("insider_name", "unknown"),
                "title": raw.get("insider_title", ""),
            })
        elif is_sell and is_recent:
            sells.append(sig)

    buy_count = len(buys)
    total_buy_value = sum(b["value"] for b in buys)

    if buy_count == 0:
        return {"score": 0.0, "buy_count": 0, "buy_value": 0, "details": "no_insider_buys"}

    # Cluster buying: multiple insiders buying = coordinated conviction
    unique_insiders = len(set(b["insider"] for b in buys))
    if unique_insiders >= 4:
        cluster_score = 1.0
    elif unique_insiders >= 3:
        cluster_score = 0.85
    elif unique_insiders >= 2:
        cluster_score = 0.65
    else:
        cluster_score = 0.35

    # Buy vs sell ratio
    total_sells = len(sells)
    if total_sells == 0 and buy_count > 0:
        ratio_score = 1.0  # All buying, no selling
    elif buy_count > total_sells * 2:
        ratio_score = 0.80
    elif buy_count > total_sells:
        ratio_score = 0.50
    else:
        ratio_score = 0.15  # More selling than buying

    # Value relative to market cap
    value_score = 0.3
    if market_cap and market_cap > 0 and total_buy_value > 0:
        ratio = total_buy_value / market_cap
        if ratio > 0.01:
            value_score = 1.0
        elif ratio > 0.005:
            value_score = 0.70
        elif ratio > 0.001:
            value_score = 0.45

    combined = 0.40 * cluster_score + 0.35 * ratio_score + 0.25 * value_score
    return {
        "score": round(combined, 4),
        "buy_count": buy_count,
        "buy_value": total_buy_value,
        "unique_insiders": unique_insiders,
        "details": f"{buy_count} insider buys by {unique_insiders} insiders",
    }


async def fetch_form4_from_edgar(cik: str) -> List[Dict[str, Any]]:
    """
    Fetch recent Form 4 filings from SEC EDGAR.
    Returns parsed insider transactions.
    """
    cik_padded = cik.zfill(10)
    url = f"{SEC_BASE}/cgi-bin/browse-edgar?action=getcompany&CIK={cik_padded}&type=4&dateb=&owner=include&count=20&search_text=&action=getcompany&output=atom"

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code != 200:
                return []

            # Parse Atom feed for Form 4 entries
            # (Basic parsing — production would use proper XML parser)
            text = resp.text
            entries = []
            for i, chunk in enumerate(text.split("<entry>")):
                if i == 0:
                    continue  # Skip header
                entry = {}
                if "<title>" in chunk:
                    title_start = chunk.index("<title>") + 7
                    title_end = chunk.index("</title>")
                    entry["title"] = chunk[title_start:title_end]
                if "<updated>" in chunk:
                    date_start = chunk.index("<updated>") + 9
                    date_end = chunk.index("</updated>")
                    entry["date"] = chunk[date_start:date_end][:10]
                entries.append(entry)

            return entries[:10]  # Latest 10
        except Exception as e:
            logger.error(f"Form 4 fetch failed for CIK {cik}: {e}")
            return []


def score_smart_money(
    signals: List[Dict[str, Any]],
    market_cap: Optional[float] = None,
    cik: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compute Lens 5 score for smart money accumulation.

    Returns:
        smart_money_score (0.0-1.0)
        institutional_buys_13f
        insider_buys_form4
        insider_buy_value_usd
        smart_money_details
    """
    # Separate signals by type. NOTE: the S8 ingesters emit `institutional_accumulation`
    # (ingest-13f) and `insider_buy_cluster`/`insider_sell_cluster` (ingest-form4);
    # the older `sec_13f`/`form_4_insider` names are kept for back-compat.
    signals_13f = [s for s in signals
                   if s.get("signal_type") in ("institutional_accumulation", "sec_13f")]
    signals_form4 = [s for s in signals
                     if s.get("signal_type") in ("insider_buy_cluster", "insider_sell_cluster",
                                                 "form_4_insider", "form_4")]

    # Score each dimension
    inst_result = _score_institutional_buying(signals_13f, market_cap)
    insider_result = _score_insider_buying(signals_form4, market_cap)

    inst_score = inst_result["score"]
    insider_score = insider_result["score"]

    # Composite: 50% institutional + 50% insider
    # Bonus if both are active (convergence signal)
    convergence_bonus = 0.0
    if inst_score > 0.3 and insider_score > 0.3:
        convergence_bonus = 0.10  # Both sides buying = strong
    if inst_score > 0.5 and insider_score > 0.5:
        convergence_bonus = 0.20

    composite = 0.50 * inst_score + 0.50 * insider_score + convergence_bonus
    composite = round(min(max(composite, 0.0), 1.0), 4)

    cited_ids = [s.get("signal_id") for s in signals if s.get("signal_id")]

    return {
        "smart_money_score": composite,
        "institutional_buys_13f": inst_result["buy_count"],
        "insider_buys_form4": insider_result["buy_count"],
        "insider_buy_value_usd": insider_result["buy_value"],
        "cited_signal_ids": cited_ids,
        "smart_money_details": {
            "components": {
                "institutional": inst_score,
                "insider": insider_score,
                "convergence_bonus": convergence_bonus,
            },
            "institutional": inst_result,
            "insider": insider_result,
            "cited_signal_ids": cited_ids,
        },
    }
