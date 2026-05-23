"""
EDGAR API Client — Form D filing ingest.
Uses EFTS search with proper URL construction from accession numbers.
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
            "Accept-Encoding": "gzip, deflate",
        })

    def get_form_d_filings(self, date_str: str) -> List[Dict[str, Any]]:
        filings = []

        # EFTS full-text search
        try:
            resp = self.session.get(
                "https://efts.sec.gov/LATEST/search-index",
                params={"q": "", "forms": "D", "dateRange": "custom",
                        "startdt": date_str, "enddt": date_str},
                timeout=30
            )
            if resp.status_code == 200:
                data = resp.json()
                hits = data.get("hits", {}).get("hits", [])
                for hit in hits:
                    src = hit.get("_source", {})
                    raw_id = hit.get("_id", "")
                    cik = str(src.get("entity_id", "") or src.get("cik", "") or "").strip()
                    entity_name = src.get("entity_name", "") or src.get("display_names", [""])[0] if isinstance(src.get("display_names"), list) else src.get("entity_name", "")
                    file_path = src.get("file_path", "")

                    # Build EDGAR URL from whatever we have
                    acc_dashes = raw_id  # keep dashes
                    acc_nodashes = raw_id.replace("-", "")

                    if file_path:
                        edgar_url = f"https://www.sec.gov/Archives/{file_path}"
                    elif cik:
                        edgar_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_dashes}/"
                    else:
                        # Use accession number to construct URL via submissions API
                        edgar_url = f"https://www.sec.gov/cgi-bin/viewer?action=view&cik={acc_nodashes[:10]}&type=D&dateb=&owner=include&count=1"

                    filings.append({
                        "accession_number": acc_nodashes,
                        "accession_formatted": acc_dashes,
                        "cik": cik.zfill(10),
                        "company_name": src.get("entity_name", ""),
                        "file_date": src.get("file_date", date_str),
                        "edgar_url": edgar_url,
                    })

                if filings:
                    log.info(f"EFTS found {len(filings)} filings. Sample URL: {filings[0]['edgar_url']}")
                elif hits:
                    # Log first hit to debug field names
                    first_src = hits[0].get("_source", {})
                    log.info(f"EFTS {len(hits)} hits. Fields: {list(first_src.keys())[:10]}. entity_id={first_src.get('entity_id')}, file_path={first_src.get('file_path')}")
                    # Still add them even without CIK
                    for hit in hits[:50]:
                        s = hit.get("_source", {})
                        rid = hit.get("_id", "")
                        if rid:
                            filings.append({
                                "accession_number": rid.replace("-", ""),
                                "accession_formatted": rid,
                                "cik": str(s.get("entity_id", "") or "").zfill(10),
                                "company_name": s.get("entity_name", "") or str(s.get("display_names", [""])),
                                "file_date": s.get("file_date", date_str),
                                "edgar_url": f"https://www.sec.gov/Archives/edgar/data/{s.get('entity_id', '0')}/{rid}/" if s.get("entity_id") else "",
                            })
                    if filings:
                        log.info(f"Added {len(filings)} from EFTS with available fields")
        except Exception as e:
            log.warning(f"EFTS search failed: {e}")

        # Fallback: daily index
        if not filings:
            filings = self._try_daily_index(date_str)

        return filings

    def _try_daily_index(self, date_str):
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            qtr = (dt.month - 1) // 3 + 1
            url = f"https://www.sec.gov/Archives/edgar/daily-index/{dt.year}/QTR{qtr}/master{dt.strftime('%Y%m%d')}.idx"
            resp = self.session.get(url, timeout=30)
            if resp.status_code != 200:
                return []
            filings = []
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
            return []

    def download_filing(self, filing_url: str) -> Optional[str]:
        if not filing_url:
            return None
        try:
            # Get the filing index page
            resp = self.session.get(filing_url, timeout=30)
            if resp.status_code == 404:
                log.debug(f"404: {filing_url}")
                return None
            resp.raise_for_status()
            content = resp.text

            # Direct XML check
            if "<edgarSubmission" in content or ("<formD" in content.lower() and "<?xml" in content[:200]):
                return content

            # HTML index page — find XML link
            # Primary doc patterns: primary_doc.xml, *-primary_doc.xml, formD.xml
            xml_patterns = [
                r'href="([^"]*primary_doc[^"]*\.xml)"',
                r'href="([^"]*formD[^"]*\.xml)"',
                r'href="([^"]*\.xml)"',
            ]
            for pattern in xml_patterns:
                xml_links = re.findall(pattern, content, re.IGNORECASE)
                if xml_links:
                    xml_filename = xml_links[0]
                    if not xml_filename.startswith("http"):
                        xml_url = filing_url.rstrip("/") + "/" + xml_filename.lstrip("/")
                    else:
                        xml_url = xml_filename
                    try:
                        xml_resp = self.session.get(xml_url, timeout=30)
                        xml_resp.raise_for_status()
                        if "edgarSubmission" in xml_resp.text or "<?xml" in xml_resp.text[:200]:
                            return xml_resp.text
                    except Exception:
                        continue

            log.debug(f"No Form D XML found at {filing_url}")
            return None
        except Exception as e:
            log.debug(f"Download error {filing_url}: {e}")
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
