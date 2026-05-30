"""
Smart Money Tracker
===================
Tracks institutional 13F filings and detects crossover investments.

13F data source: SEC EDGAR EFTS (free, public, rate-limited to 10 req/sec)
Form D cross-reference: our own signals database

Key detection:
  When a fund known for PUBLIC equities (13F filer) also appears in
  a PRIVATE placement (Form D), that company is likely pre-IPO.
"""
import os
import logging
import re
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

log = logging.getLogger(__name__)

EDGAR_EFTS = "https://efts.sec.gov/LATEST/search-index"
EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions"

# 13F is filed 45 days AFTER quarter-end, so accumulation is confirmation only —
# never a primary trigger. Cap its signal value accordingly (Sprint 8.7).
ACCUMULATION_MAX_VALUE = 0.6


def parse_13f_infotable(xml_text: str) -> List[Dict[str, Any]]:
    """Parse a 13F information table XML into holdings (Sprint 8.7, pure/testable).

    Returns [{issuer_name, cusip, value_usd, shares}, ...]. Handles the namespaced
    <infoTable> elements regardless of namespace prefix.
    """
    holdings: List[Dict[str, Any]] = []
    if not xml_text:
        return holdings
    # Strip namespaces to simplify matching (13F XML uses varying ns prefixes).
    text = re.sub(r"<(/?)(\w+:)", r"<\1", xml_text)
    blocks = re.findall(r"<infoTable>(.*?)</infoTable>", text, re.DOTALL | re.IGNORECASE)
    for block in blocks:
        def _grab(tag: str) -> Optional[str]:
            m = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.DOTALL | re.IGNORECASE)
            return m.group(1).strip() if m else None

        name = _grab("nameOfIssuer")
        cusip = _grab("cusip")
        value_raw = _grab("value")
        shares = _grab("sshPrnamt")
        try:
            # 13F "value" historically in $thousands; post-2023 in whole dollars.
            value_usd = float(value_raw.replace(",", "")) if value_raw else None
        except (ValueError, AttributeError):
            value_usd = None
        try:
            shares_n = float(shares.replace(",", "")) if shares else None
        except (ValueError, AttributeError):
            shares_n = None
        if name:
            holdings.append({
                "issuer_name": name,
                "cusip": cusip,
                "value_usd": value_usd,
                "shares": shares_n,
            })
    return holdings


def accumulation_signal_value(market_cap_usd: Optional[float]) -> float:
    """Confirmation-only signal value for institutional accumulation (Sprint 8.7).

    A top fund ENTERING a small/ignored name is the strongest confirmation —
    but still capped (13F is 45d delayed). Larger caps = weaker signal.
    """
    if market_cap_usd is None:
        return 0.4
    mc_m = market_cap_usd / 1e6
    if mc_m < 300:
        v = 0.6
    elif mc_m < 1000:
        v = 0.5
    elif mc_m < 5000:
        v = 0.35
    else:
        v = 0.2
    return min(v, ACCUMULATION_MAX_VALUE)


class SmartMoneyTracker:
    def __init__(self, tracked_funds: Dict[str, str]):
        self.tracked_funds = tracked_funds
        self.user_agent = os.environ.get("EDGAR_USER_AGENT", "Alpha0Engine contact@alpha0engine.com")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

    def get_recent_13f_filings(self, days_back: int = 7) -> List[Dict[str, Any]]:
        """Search EDGAR for recent 13F-HR filings from tracked funds."""
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        filings = []
        for fund_name, fund_key in self.tracked_funds.items():
            try:
                params = {
                    "q": fund_name,
                    "forms": "13F-HR,13F-HR/A",
                    "dateRange": "custom",
                    "startdt": start_date,
                    "enddt": end_date,
                }
                resp = self.session.get(EDGAR_EFTS, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                for hit in data.get("hits", {}).get("hits", []):
                    src = hit.get("_source", {})
                    filings.append({
                        "fund_name": fund_name,
                        "fund_key": fund_key,
                        "accession": hit.get("_id", ""),
                        "file_date": src.get("file_date", ""),
                        "cik": src.get("entity_id", ""),
                    })

                import time
                time.sleep(0.15)
            except Exception as e:
                log.warning(f"Error searching 13F for {fund_name}: {e}")

        return filings

    def process_13f_filing(self, filing: Dict[str, Any]) -> None:
        """Process a 13F filing and write crossover_filing signals."""
        try:
            import asyncio
            from shared.clients.postgres import AsyncSessionLocal
            from shared.schemas.signals import Signal
            import uuid

            signal = Signal(
                id=str(uuid.uuid4()),
                entity_id="UNRESOLVED",
                signal_type="crossover_filing",
                signal_date=datetime.strptime(
                    filing.get("file_date") or datetime.utcnow().strftime("%Y-%m-%d"),
                    "%Y-%m-%d"
                ),
                value=0.7,  # 13F filing = strong institutional interest
                raw_data=filing,
                source="sec_13f",
                source_id=filing.get("accession"),
                notes=f"13F: {filing['fund_name']}",
            )

            async def _w():
                async with AsyncSessionLocal() as s:
                    s.add(signal)
                    await s.commit()

            asyncio.get_event_loop().run_until_complete(_w())
        except Exception as e:
            log.error(f"Failed to write 13F signal: {e}")

    async def emit_institutional_accumulation(
        self,
        *,
        entity_id: str,
        ticker: Optional[str],
        fund_name: str,
        market_cap_usd: Optional[float],
        accession: str,
        holding: Dict[str, Any],
    ) -> None:
        """Write an `institutional_accumulation` confirmation signal (Sprint 8.7).

        Confirmation only — value is capped (see accumulation_signal_value). The
        smart-money lens reads this to corroborate a thesis, never to originate one.
        """
        from shared.clients.postgres import AsyncSessionLocal
        from shared.schemas.signals import Signal
        import uuid

        value = accumulation_signal_value(market_cap_usd)
        signal = Signal(
            id=str(uuid.uuid4()),
            entity_id=entity_id,
            signal_type="institutional_accumulation",
            signal_date=datetime.utcnow(),
            value=value,
            raw_data={
                "fund": fund_name,
                "ticker": ticker,
                "holding_value_usd": holding.get("value_usd"),
                "shares": holding.get("shares"),
                "cusip": holding.get("cusip"),
                "confirmation_only": True,
                "lane_agnostic": True,
            },
            source="sec_13f",
            source_id=f"accum-{accession}-{entity_id}",
            notes=f"13F accumulation: {fund_name} holds {ticker or holding.get('issuer_name')}",
        )
        async with AsyncSessionLocal() as s:
            s.add(signal)
            await s.commit()

    async def detect_crossover_investments(self) -> List[Dict[str, Any]]:
        """Cross-reference: find tracked fund names in Form D related_persons."""
        from shared.clients.postgres import AsyncSessionLocal
        from shared.schemas.signals import Signal
        from sqlmodel import select

        crossovers = []
        async with AsyncSessionLocal() as session:
            # Get recent Form D filings
            result = await session.exec(
                select(Signal)
                .where(Signal.signal_type == "form_d")
                .where(Signal.signal_date >= datetime.utcnow() - timedelta(days=90))
                .limit(1000)
            )
            form_d_signals = result.all()

        for sig in form_d_signals:
            rd = sig.raw_data or {}
            persons = rd.get("related_persons", [])
            company = rd.get("company_name", "")

            for person in persons:
                person_name = (person.get("name", "") or "").upper()
                for fund_name in self.tracked_funds:
                    # Check if any tracked fund name appears in related persons
                    fund_words = fund_name.split()[:2]
                    if all(w in person_name for w in fund_words):
                        crossover = {
                            "fund": fund_name,
                            "company": company,
                            "entity_id": sig.entity_id,
                            "form_d_date": str(sig.signal_date),
                            "offering_amount": rd.get("total_offering_amount"),
                        }
                        crossovers.append(crossover)
                        log.info(f"CROSSOVER DETECTED: {fund_name} -> {company}")

                        # Write high-value signal
                        await self._write_crossover_signal(sig, fund_name)

        return crossovers

    async def _write_crossover_signal(self, form_d_signal, fund_name: str) -> None:
        """Write a high-value crossover investment signal."""
        from shared.clients.postgres import AsyncSessionLocal
        from shared.schemas.signals import Signal
        import uuid

        signal = Signal(
            id=str(uuid.uuid4()),
            entity_id=form_d_signal.entity_id,
            signal_type="crossover_filing",
            signal_date=datetime.utcnow(),
            value=0.9,  # Crossover = strongest pre-IPO signal
            raw_data={
                "fund": fund_name,
                "company": (form_d_signal.raw_data or {}).get("company_name"),
                "form_d_accession": form_d_signal.source_id,
                "offering_amount": (form_d_signal.raw_data or {}).get("total_offering_amount"),
            },
            source="sec_13f",
            source_id=f"crossover-{form_d_signal.source_id}-{fund_name}",
            notes=f"CROSSOVER: {fund_name} invested in private company",
        )

        async with AsyncSessionLocal() as s:
            s.add(signal)
            await s.commit()
