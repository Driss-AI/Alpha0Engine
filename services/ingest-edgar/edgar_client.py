"""
EDGAR API Client — EFTS search + filing download.
Fair Access: User-Agent required, max 10 req/sec.
"""
import os, logging, requests, re
from typing import List, Dict, Any, Optional

log = logging.getLogger(__name__)

EDGAR_EFTS = "https://efts.sec.gov/LATEST/search-index"
EDGAR_FULL_TEXT = "https://efts.sec.gov/LATEST/search-index"
EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"


class EdgarClient:
    def __init__(self):
        self.user_agent = os.environ.get("EDGAR_USER_AGENT", "Alpha0Engine contact@alpha0engine.com")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"})

    def get_form_d_filings(self, date_str: str) -> List[Dict[str, Any]]:
        """Use EDGAR full-text search API to find Form D filings."""
        try:
            # Use the correct EDGAR full-text search endpoint
            url = "https://efts.sec.gov/LATEST/search-index"
            params = {
                "q": "",
                "forms": "D",
                "dateRange": "custom",
                "startdt": date_str,
                "enddt": date_str,
            }
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.error(f"EDGAR EFTS error: {e}")
            return []

        filings = []
        for hit in data.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            file_num = src.get("file_num", "")
            entity_name = src.get("entity_name", "")
            file_date = src.get("file_date", date_str)

            # Build the filing URL from the file path
            file_path = src.get("file_path", "")
            if not file_path:
                continue

            filings.append({
                "accession_number": hit.get("_id", "").replace("-", ""),
                "cik": str(src.get("entity_id", "")).zfill(10),
                "company_name": entity_name,
                "file_date": file_date,
                "file_path": file_path,
                "edgar_url": f"https://www.sec.gov/Archives/{file_path}" if file_path else "",
            })

        return filings

    def download_filing(self, filing_url: str) -> Optional[str]:
        """Download Form D XML directly."""
        if not filing_url:
            return None
        try:
            # Try direct download first
            resp = self.session.get(filing_url, timeout=30)
            resp.raise_for_status()
            content = resp.text

            # Check if we got XML or HTML
            if content.strip().startswith("<?xml") or "<edgarSubmission" in content:
                return content

            # If HTML, try to find the primary XML document link
            xml_links = re.findall(r'href="([^"]*primary_doc\.xml[^"]*)"', content, re.IGNORECASE)
            if not xml_links:
                xml_links = re.findall(r'href="([^"]+\.xml)"', content, re.IGNORECASE)

            if xml_links:
                # Build absolute URL
                base_url = filing_url.rsplit("/", 1)[0] if "/" in filing_url else filing_url
                xml_url = xml_links[0]
                if not xml_url.startswith("http"):
                    xml_url = base_url + "/" + xml_url.lstrip("/")

                xml_resp = self.session.get(xml_url, timeout=30)
                xml_resp.raise_for_status()
                if xml_resp.text.strip().startswith("<?xml") or "<edgarSubmission" in xml_resp.text:
                    return xml_resp.text

            log.warning(f"No XML found at {filing_url}")
            return None

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
