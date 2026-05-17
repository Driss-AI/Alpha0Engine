"""
EDGAR API Client — EFTS search + filing download.
Fair Access: User-Agent required, max 10 req/sec.
"""
import os, logging, requests, re
from typing import List, Dict, Any, Optional

log = logging.getLogger(__name__)
EDGAR_EFTS = "https://efts.sec.gov/LATEST/search-index"
EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"


class EdgarClient:
    def __init__(self):
        self.user_agent = os.environ.get("EDGAR_USER_AGENT", "Alpha0Engine contact@alpha0engine.com")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"})

    def get_form_d_filings(self, date_str: str) -> List[Dict[str, Any]]:
        params = {"q": "", "forms": "D", "dateRange": "custom", "startdt": date_str, "enddt": date_str}
        try:
            resp = self.session.get(EDGAR_EFTS, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.error(f"EDGAR EFTS error: {e}")
            return []
        filings = []
        for hit in data.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            accession = hit.get("_id", "").replace("-", "")
            cik = str(src.get("entity_id", "")).zfill(10)
            acc_fmt = f"{accession[:10]}-{accession[10:12]}-{accession[12:]}"
            filings.append({
                "accession_number": accession, "cik": cik,
                "company_name": src.get("entity_name", ""),
                "file_date": src.get("file_date", date_str),
                "edgar_url": f"{EDGAR_ARCHIVES}/{cik}/{acc_fmt}",
            })
        return filings

    def download_filing(self, filing_url: str) -> Optional[str]:
        if not filing_url:
            return None
        try:
            resp = self.session.get(filing_url + "-index.htm", timeout=30)
            resp.raise_for_status()
            matches = re.findall(r'href="([^"]+\.xml)"', resp.text, re.IGNORECASE)
            if not matches:
                return None
            xml_url = filing_url.rsplit("/", 1)[0] + "/" + matches[0]
            return self.session.get(xml_url, timeout=30).text
        except Exception as e:
            log.warning(f"Download failed {filing_url}: {e}")
            return None

    def archive_to_r2(self, parsed: Dict, raw_xml: str, date_str: str) -> None:
        try:
            import asyncio
            from shared.clients.r2 import r2_key, upload
            key = r2_key("edgar", "form_d", date_str, parsed.get("accession_number", "unknown"))
            asyncio.get_event_loop().run_until_complete(upload(key, raw_xml, "text/xml"))
        except Exception as e:
            log.warning(f"R2 archive failed (non-fatal): {e}")

    def write_signal(self, parsed: Dict) -> None:
        try:
            import asyncio
            from datetime import datetime
            from shared.clients.postgres import AsyncSessionLocal
            from shared.schemas.signals import Signal
            signal = Signal(
                entity_id=parsed.get("entity_id", "UNRESOLVED"),
                signal_type="form_d",
                signal_date=datetime.fromisoformat(parsed.get("file_date", datetime.utcnow().isoformat())),
                value=0.5, raw_data=parsed, source="edgar",
                source_id=parsed.get("accession_number"),
            )
            async def _w():
                async with AsyncSessionLocal() as s:
                    s.add(signal)
                    await s.commit()
            asyncio.get_event_loop().run_until_complete(_w())
        except Exception as e:
            log.error(f"DB write failed: {e}")

    def publish_to_stream(self, parsed: Dict) -> None:
        try:
            import asyncio
            from shared.clients.redis_client import publish_signal
            asyncio.get_event_loop().run_until_complete(publish_signal(parsed))
        except Exception as e:
            log.warning(f"Redis publish failed (non-fatal): {e}")
