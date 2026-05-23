"""
EDGAR API Client — uses multiple fallback methods for Form D filings.
Method 1: EFTS full-text search
Method 2: Company search (Atom feed)
Method 3: Daily index files
"""
import os, logging, requests, re
from typing import List, Dict, Any, Optional
from datetime import datetime

log = logging.getLogger(__name__)


class EdgarClient:
    def __init__(self):
        self.user_agent = os.environ.get("EDGAR_USER_AGENT", "Alpha0Engine contact@alpha0engine.com")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/html, application/atom+xml",
            "Accept-Encoding": "gzip, deflate",
        })

    def get_form_d_filings(self, date_str: str) -> List[Dict[str, Any]]:
        filings = []

        # Method 1: EFTS full-text search
        try:
            resp = self.session.get(
                "https://efts.sec.gov/LATEST/search-index",
                params={"q": "", "forms": "D", "dateRange": "custom", "startdt": date_str, "enddt": date_str},
                timeout=30
            )
            if resp.status_code == 200:
                data = resp.json()
                for hit in data.get("hits", {}).get("hits", []):
                    src = hit.get("_source", {})
                    fp = src.get("file_path", "")
                    filings.append({
                        "accession_number": hit.get("_id", "").replace("-", ""),
                        "cik": str(src.get("entity_id", "")).zfill(10),
                        "company_name": src.get("entity_name", ""),
                        "file_date": src.get("file_date", date_str),
                        "edgar_url": f"https://www.sec.gov/Archives/{fp}" if fp else "",
                    })
                if filings:
                    log.info(f"EFTS found {len(filings)} Form D filings")
                    return filings
        except Exception as e:
            log.warning(f"EFTS failed: {e}")

        # Method 2: Daily index file
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            qtr = (dt.month - 1) // 3 + 1
            idx_url = f"https://www.sec.gov/Archives/edgar/daily-index/{dt.year}/QTR{qtr}/master{dt.strftime('%Y%m%d')}.idx"
            resp = self.session.get(idx_url, timeout=30)
            if resp.status_code == 200:
                for line in resp.text.splitlines():
                    parts = line.split("|")
                    if len(parts) >= 5 and parts[2].strip() in ("D", "D/A"):
                        filings.append({
                            "accession_number": parts[4].strip().split("/")[-1].replace("-","").replace(".txt",""),
                            "cik": parts[0].strip().zfill(10),
                            "company_name": parts[1].strip(),
                            "file_date": parts[3].strip() or date_str,
                            "edgar_url": f"https://www.sec.gov/Archives/{parts[4].strip()}",
                        })
                if filings:
                    log.info(f"Daily index found {len(filings)} Form D filings")
                    return filings
        except Exception as e:
            log.warning(f"Daily index failed: {e}")

        log.info(f"No Form D filings found for {date_str} (may be weekend/holiday)")
        return filings

    def download_filing(self, filing_url: str) -> Optional[str]:
        if not filing_url:
            return None
        try:
            resp = self.session.get(filing_url, timeout=30)
            resp.raise_for_status()
            content = resp.text
            if "<edgarSubmission" in content or "<?xml" in content[:100]:
                return content
            # HTML index — find XML link
            xml_links = re.findall(r'href="([^"]*primary_doc\.xml[^"]*)"', content, re.IGNORECASE)
            if not xml_links:
                xml_links = re.findall(r'href="([^"]+\.xml)"', content, re.IGNORECASE)
            if xml_links:
                base = filing_url.rsplit("/", 1)[0]
                xml_url = xml_links[0] if xml_links[0].startswith("http") else base + "/" + xml_links[0].lstrip("/")
                xml_resp = self.session.get(xml_url, timeout=30)
                if "<edgarSubmission" in xml_resp.text or "<?xml" in xml_resp.text[:100]:
                    return xml_resp.text
            return None
        except Exception as e:
            log.warning(f"Download failed {filing_url}: {e}")
            return None

    def archive_to_r2(self, parsed, raw_xml, date_str):
        try:
            import asyncio
            from shared.clients.r2 import r2_key, upload
            key = r2_key("edgar", "form_d", date_str, parsed.get("accession_number", "unknown"))
            asyncio.get_event_loop().run_until_complete(upload(key, raw_xml, "text/xml"))
        except Exception as e:
            log.warning(f"R2 archive failed (non-fatal): {e}")

    def write_signal(self, parsed):
        try:
            import asyncio
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

    def publish_to_stream(self, parsed):
        try:
            import asyncio
            from shared.clients.redis_client import publish_signal
            asyncio.get_event_loop().run_until_complete(publish_signal(parsed))
        except Exception as e:
            log.warning(f"Redis publish failed (non-fatal): {e}")
