"""
Evidence recorder (Sprint 9.1) — shared helper.

Builds evidence_items rows from a candidate's signals so every lens score traces
to source URLs. Used by the screener after scoring; the thesis generator and the
Telegram alert read these rows back.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.evidence_item import EvidenceItem

# Map a signal source/type to (evidence source label, source_url builder).
_SOURCE_LABEL = {
    "clinicaltrials_gov": "ct_gov",
    "edgar_8k": "sec",
    "edgar": "sec",
    "sec_13f": "13f",
    "finnhub": "news",
    "ingest_prices": "prices",
}


def _signal_to_evidence_source(signal: dict[str, Any]) -> str:
    src = (signal.get("source") or "").lower()
    if src in _SOURCE_LABEL:
        return _SOURCE_LABEL[src]
    stype = (signal.get("signal_type") or "").lower()
    if "form_4" in stype or "insider" in stype:
        return "form4"
    if "trial" in stype:
        return "ct_gov"
    if "13f" in stype or "institutional" in stype:
        return "13f"
    if "8k" in stype or stype == "red_flag":
        return "sec"
    if "news" in stype:
        return "news"
    return "sec"


def _signal_source_url(signal: dict[str, Any]) -> Optional[str]:
    raw = signal.get("raw_data") or {}
    # Common URL fields across sources
    for key in ("source_url", "url", "filing_url"):
        if raw.get(key):
            return raw[key]
    # ClinicalTrials
    if raw.get("nct_id"):
        return f"https://clinicaltrials.gov/study/{raw['nct_id']}"
    # SEC accession → company filing index
    if raw.get("cik"):
        return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={raw['cik']}"
    return None


async def record_evidence(
    session: AsyncSession,
    *,
    entity_id: str,
    ticker: Optional[str],
    lane_id: Optional[str],
    signals: list[dict[str, Any]],
    max_items: int = 12,
) -> int:
    """Upsert evidence_items from a candidate's signals. Returns count recorded.

    Only signals with a derivable source_url become evidence (so every item is
    clickable). Dedupe on (entity_id, lane_id, source_url). Does NOT commit.
    """
    recorded = 0
    seen: set[str] = set()
    for sig in signals:
        if recorded >= max_items:
            break
        url = _signal_source_url(sig)
        if not url or url in seen:
            continue
        seen.add(url)

        existing = (await session.execute(
            select(EvidenceItem).where(
                EvidenceItem.entity_id == entity_id,
                EvidenceItem.lane_id == lane_id,
                EvidenceItem.source_url == url,
            )
        )).scalar_one_or_none()
        if existing is not None:
            continue

        summary = (sig.get("notes") or "")[:300] or sig.get("signal_type")
        session.add(EvidenceItem(
            entity_id=entity_id,
            ticker=ticker,
            lane_id=lane_id,
            signal_id=sig.get("signal_id"),
            lens=sig.get("signal_type"),
            source=_signal_to_evidence_source(sig),
            source_url=url,
            summary=summary,
            extra={"value": sig.get("value")},
        ))
        recorded += 1
    return recorded
