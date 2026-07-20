"""
Shared SEC EDGAR client bits for the merged SEC module (8-K, Form 4, 13F).

EDGAR Fair Access: max 10 req/sec, User-Agent required.
"""
import os
from typing import Any, Dict, List, Optional

import httpx

EDGAR_UA = os.environ.get("EDGAR_USER_AGENT", "Alpha0Engine contact@alpha0engine.com")
HEADERS = {"User-Agent": EDGAR_UA}
JSON_HEADERS = {"User-Agent": EDGAR_UA, "Accept": "application/json"}
XML_HEADERS = {"User-Agent": EDGAR_UA, "Accept": "text/xml, application/xml"}
SEC_DELAY = 0.12  # 10 req/sec

EFTS_SEARCH = "https://efts.sec.gov/LATEST/search-index"
SEC_BASE = "https://data.sec.gov"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"


def archive_url(cik: str, accession: str, doc: str) -> str:
    """URL of a filing document under EDGAR archives."""
    return f"{SEC_ARCHIVES}/{cik}/{accession.replace('-', '')}/{doc}"


async def efts_search(
    client: httpx.AsyncClient,
    *,
    forms: str,
    startdt: str,
    enddt: str,
    q: str = "",
) -> List[Dict[str, Any]]:
    """Full-text search hits ({_id, _source}) for a form type and date range."""
    params = {"q": q, "forms": forms, "dateRange": "custom",
              "startdt": startdt, "enddt": enddt}
    resp = await client.get(EFTS_SEARCH, params=params, headers=HEADERS)
    resp.raise_for_status()
    return resp.json().get("hits", {}).get("hits", [])


async def fetch_archive_doc(
    client: httpx.AsyncClient,
    cik: str,
    accession: str,
    doc: str,
    *,
    xml: bool = False,
) -> Optional[str]:
    """Download a filing document; None on any failure."""
    try:
        resp = await client.get(
            archive_url(cik, accession, doc),
            headers=XML_HEADERS if xml else HEADERS,
        )
        return resp.text if resp.status_code == 200 else None
    except Exception:
        return None
