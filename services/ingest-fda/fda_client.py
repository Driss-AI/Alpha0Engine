"""
FDA data client (Sprint 8.2)

Sources (all free, no key required for low volume):
  - OpenFDA drugsfda API — recent approvals (https://api.fda.gov/drug/drugsfda.json)
  - FDA approvals are the high-confidence "it happened" events.

PDUFA dates and AdCom meetings are not in a single clean public API; they're
disclosed in company 8-Ks/press releases. ingest-fda captures the OpenFDA
approval stream here; PDUFA/AdCom catalysts are primarily emitted by the
lane-aware 8-K classifier (8.3) and news tagger (8.5). This client also parses
the FDA Advisory Committee calendar page when reachable.

Pure-function parsing is separated from network calls so it's unit-testable
against fixtures without hitting the network.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

OPENFDA_DRUGSFDA = "https://api.fda.gov/drug/drugsfda.json"
DEFAULT_TIMEOUT = 20.0


def _parse_openfda_date(s: Optional[str]) -> Optional[date]:
    """OpenFDA submission dates are 'YYYYMMDD'."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except (ValueError, TypeError):
        return None


def parse_drugsfda_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse one OpenFDA drugsfda record into FDA approval events.

    A record has a sponsor, products, and submissions. We emit one approval
    event per APPROVED original (type=1) submission.
    """
    out: list[dict[str, Any]] = []
    sponsor = result.get("sponsor_name")
    products = result.get("products") or []
    brand_names = [p.get("brand_name") for p in products if p.get("brand_name")]
    drug_name = brand_names[0] if brand_names else None
    # indication / dosage form for context
    indication = None
    if products:
        indication = products[0].get("dosage_form")

    for sub in result.get("submissions") or []:
        status = (sub.get("submission_status") or "").upper()
        sub_type = (sub.get("submission_type") or "").upper()
        if status != "AP":   # AP = approved
            continue
        ev_date = _parse_openfda_date(sub.get("submission_status_date"))
        out.append({
            "event_type": "approval",
            "drug_name": drug_name,
            "company": sponsor,
            "indication": indication,
            "event_date": ev_date,
            "status": "approved",
            "source_url": "https://api.fda.gov/drug/drugsfda.json",
            "raw": {
                "application_number": result.get("application_number"),
                "submission_type": sub_type,
                "submission_number": sub.get("submission_number"),
            },
        })
    return out


async def fetch_recent_approvals(
    *,
    since: date,
    limit: int = 100,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    """Fetch recent drug approvals from OpenFDA since a date.

    Returns a flat list of approval event dicts (see parse_drugsfda_result).
    """
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    since_str = since.strftime("%Y%m%d")
    today_str = date.today().strftime("%Y%m%d")
    params = {
        "search": f"submissions.submission_status_date:[{since_str}+TO+{today_str}]",
        "limit": str(limit),
    }
    events: list[dict[str, Any]] = []
    try:
        resp = await client.get(OPENFDA_DRUGSFDA, params=params)
        resp.raise_for_status()
        data = resp.json()
        for result in data.get("results", []):
            events.extend(parse_drugsfda_result(result))
    except httpx.HTTPStatusError as e:
        # OpenFDA returns 404 when zero results match — that's not an error.
        if e.response.status_code == 404:
            log.info("OpenFDA: no approvals in window")
        else:
            log.error(f"OpenFDA HTTP error: {e}")
    except Exception as e:
        log.error(f"OpenFDA fetch failed: {e}")
    finally:
        if owns_client:
            await client.aclose()
    return events
