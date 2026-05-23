"""
Public Equity Screener
======================
Fetches financial metrics for public companies via free SEC EDGAR XBRL API.
Identifies early-stage dominance: R&D/mktcap, gross margin velocity, cash runway.
"""
import os
import logging
import httpx
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

SEC_BASE = "https://data.sec.gov"
EDGAR_UA = os.environ.get("EDGAR_USER_AGENT", "Alpha0Engine contact@alpha0engine.com")
HEADERS = {"User-Agent": EDGAR_UA, "Accept": "application/json"}


async def fetch_company_facts(cik: str) -> Optional[Dict[str, Any]]:
    """
    Pull company financial facts from SEC EDGAR XBRL companyfacts API.
    Free, no API key needed. Returns full XBRL dataset.
    """
    cik_padded = cik.zfill(10)
    url = f"{SEC_BASE}/api/xbrl/companyfacts/CIK{cik_padded}.json"

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"SEC XBRL returned {resp.status_code} for CIK {cik}")
            return None
        except Exception as e:
            logger.error(f"SEC XBRL fetch failed for CIK {cik}: {e}")
            return None


def _extract_latest(facts: Dict, taxonomy: str, concept: str) -> Optional[float]:
    """Extract the most recent annual value for a given XBRL concept."""
    try:
        units = facts["facts"][taxonomy][concept]["units"]
        # Prefer USD, fall back to any
        values = units.get("USD", units.get("USD/shares", next(iter(units.values()), [])))
        # Filter for 10-K annual filings
        annual = [v for v in values if v.get("form") == "10-K"]
        if not annual:
            annual = [v for v in values if v.get("form") in ("10-K", "10-K/A", "20-F")]
        if not annual:
            annual = values
        if annual:
            # Sort by end date, get latest
            annual.sort(key=lambda x: x.get("end", ""), reverse=True)
            return float(annual[0]["val"])
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    return None


def _extract_quarterly_series(facts: Dict, taxonomy: str, concept: str, n: int = 8) -> list:
    """Extract last N quarterly values for trend analysis."""
    try:
        units = facts["facts"][taxonomy][concept]["units"]
        values = units.get("USD", next(iter(units.values()), []))
        quarterly = [v for v in values if v.get("form") in ("10-Q", "10-Q/A")]
        quarterly.sort(key=lambda x: x.get("end", ""))
        return quarterly[-n:]
    except (KeyError, IndexError, TypeError):
        return []


async def screen_public_equity(cik: str) -> Dict[str, Any]:
    """
    Screen a public company's fundamentals.
    Returns metrics dict with all available financial indicators.
    """
    facts = await fetch_company_facts(cik)
    if not facts:
        return {"error": "no_xbrl_data", "cik": cik}

    entity_name = facts.get("entityName", "Unknown")

    # ── Key Financial Metrics ──────────────────────────────
    revenue = _extract_latest(facts, "us-gaap", "Revenues") or \
              _extract_latest(facts, "us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax") or \
              _extract_latest(facts, "us-gaap", "SalesRevenueNet")

    rd_expense = _extract_latest(facts, "us-gaap", "ResearchAndDevelopmentExpense")

    gross_profit = _extract_latest(facts, "us-gaap", "GrossProfit")

    total_assets = _extract_latest(facts, "us-gaap", "Assets")

    cash = _extract_latest(facts, "us-gaap", "CashAndCashEquivalentsAtCarryingValue") or \
           _extract_latest(facts, "us-gaap", "Cash")

    total_liabilities = _extract_latest(facts, "us-gaap", "Liabilities")

    net_income = _extract_latest(facts, "us-gaap", "NetIncomeLoss")

    operating_expenses = _extract_latest(facts, "us-gaap", "OperatingExpenses")

    shares_outstanding = _extract_latest(facts, "dei", "EntityCommonStockSharesOutstanding")

    # ── Derived Metrics ────────────────────────────────────
    gross_margin = None
    if gross_profit and revenue and revenue > 0:
        gross_margin = round(gross_profit / revenue, 4)

    # Gross margin velocity: compare last 2 quarterly gross margins
    gp_series = _extract_quarterly_series(facts, "us-gaap", "GrossProfit")
    rev_series = _extract_quarterly_series(facts, "us-gaap", "Revenues")
    gm_velocity = None
    if len(gp_series) >= 2 and len(rev_series) >= 2:
        try:
            gm_recent = float(gp_series[-1]["val"]) / float(rev_series[-1]["val"])
            gm_prior = float(gp_series[-2]["val"]) / float(rev_series[-2]["val"])
            gm_velocity = round(gm_recent - gm_prior, 4)
        except (ValueError, ZeroDivisionError):
            pass

    # Cash runway
    cash_runway = None
    if cash and operating_expenses and operating_expenses > 0 and revenue:
        monthly_burn = max((operating_expenses - (revenue or 0)) / 12, 0)
        if monthly_burn > 0:
            cash_runway = round(cash / monthly_burn, 1)

    # Revenue growth YoY
    rev_yoy = None
    rev_annual = _extract_quarterly_series(facts, "us-gaap", "Revenues", n=12)
    if len(rev_annual) >= 5:
        try:
            recent_4q = sum(float(v["val"]) for v in rev_annual[-4:])
            prior_4q = sum(float(v["val"]) for v in rev_annual[-8:-4])
            if prior_4q > 0:
                rev_yoy = round((recent_4q - prior_4q) / prior_4q, 4)
        except (ValueError, ZeroDivisionError):
            pass

    # Rule of 40 (revenue growth % + profit margin %)
    rule_of_40 = None
    if rev_yoy is not None and net_income is not None and revenue and revenue > 0:
        profit_margin = net_income / revenue
        rule_of_40 = round((rev_yoy * 100) + (profit_margin * 100), 2)

    return {
        "cik": cik,
        "entity_name": entity_name,
        "revenue": revenue,
        "rd_expense": rd_expense,
        "gross_profit": gross_profit,
        "gross_margin": gross_margin,
        "gross_margin_velocity": gm_velocity,
        "revenue_growth_yoy": rev_yoy,
        "cash": cash,
        "cash_runway_months": cash_runway,
        "net_income": net_income,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "shares_outstanding": shares_outstanding,
        "rule_of_40": rule_of_40,
        "screened_at": datetime.utcnow().isoformat(),
    }
