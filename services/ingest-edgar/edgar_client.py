"""
EDGAR API Client — Form D filing ingest via EFTS.
Field mapping (from actual EFTS response):
  _id: "CIK-ACC:filename" e.g. "0002031239-26-000001:primary_doc.xml"
  ciks: list of CIK strings e.g. ["0002031239"]
  adsh: accession number
  display_names: list e.g. ["Junction Health, Inc.  (CIK 0002031239)"]
  file_date: "2026-05-22"
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
        try:
            resp = self.session.get(
                "https://efts.sec.gov/LATEST/search-index",
                params={"q": "", "forms": "D", "dateRange": "custom",
                        "startdt": date_str, "enddt": date_str},
                timeout=30
            )
            if resp.status_code == 200:
                data = resp.json()
                for hit in data.get("hits", {}).get("hits", []):
                    src = hit.get("_source", {})
                    raw_id = hit.get("_id", "")

                    # ciks is a LIST — extract first element
                    ciks = src.get("ciks", [])
                    cik = ciks[0] if isinstance(ciks, list) and ciks else ""

                    # Accession from adsh field, or parse from _id
                    adsh = src.get("adsh", "")
                    # Extract primary doc filename and accession from _id
                    # _id format: "0002031239-26-000001:primary_doc.xml"
                    primary_doc = ""
                    if ":" in raw_id:
                        adsh_part, primary_doc = raw_id.split(":", 1)
                    else:
                        adsh_part = raw_id
                    if not adsh:
                        adsh = src.get("adsh", adsh_part)

                    # Company name from display_names list
                    names = src.get("display_names", [])
                    company_name = names[0].split("(")[0].strip() if isinstance(names, list) and names else ""

                    if not cik or not adsh:
                        continue

                    # EDGAR URL: CIK without leading zeros, accession without dashes
                    cik_stripped = str(int(cik))  # remove leading zeros
                    acc_nodashes = adsh.replace("-", "")
                    
                    # Build direct XML URL if we know the filename
                    if primary_doc:
                        edgar_url = f"https://www.sec.gov/Archives/edgar/data/{cik_stripped}/{acc_nodashes}/{primary_doc}"
                    else:
                        edgar_url = f"https://www.sec.gov/Archives/edgar/data/{cik_stripped}/{acc_nodashes}/"

                    filings.append({
                        "accession_number": adsh.replace("-", ""),
                        "accession_formatted": adsh,
                        "cik": cik.zfill(10),
                        "company_name": company_name,
                        "file_date": src.get("file_date", date_str),
                        "edgar_url": edgar_url,
                    })

                if filings:
                    log.info(f"EFTS: {len(filings)} filings. First: {filings[0]['company_name']} CIK={filings[0]['cik']}")
        except Exception as e:
            log.warning(f"EFTS failed: {e}")

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
                log.info(f"Daily index: {len(filings)} Form D filings")
            return filings
        except Exception as e:
            log.warning(f"Daily index failed: {e}")
            return []

    def download_filing(self, filing_url: str) -> Optional[str]:
        if not filing_url:
            return None
        try:
            resp = self.session.get(filing_url, timeout=30)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            content = resp.text

            # Direct XML
            if "<edgarSubmission" in content or ("<?xml" in content[:200] and "formD" in content.lower()):
                return content

            # HTML index — find primary_doc.xml or any XML
            for pattern in [r'href="([^"]*primary_doc[^"]*\.xml)"', r'href="([^"]*\.xml)"']:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    xml_fn = matches[0]
                    xml_url = xml_fn if xml_fn.startswith("http") else filing_url.rstrip("/") + "/" + xml_fn.lstrip("/")
                    try:
                        xr = self.session.get(xml_url, timeout=30)
                        xr.raise_for_status()
                        if "edgarSubmission" in xr.text or "<?xml" in xr.text[:200]:
                            return xr.text
                    except Exception:
                        continue
            return None
        except Exception as e:
            log.debug(f"Download error: {e}")
            return None

    def archive_to_r2(self, parsed, raw_xml, date_str):
        try:
            import asyncio
            from shared.clients.r2 import r2_key, upload
            key = r2_key("edgar", "form_d", date_str, parsed.get("accession_number", "unknown"))
            asyncio.get_event_loop().run_until_complete(upload(key, raw_xml, "text/xml"))
        except Exception:
            pass

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
        except Exception:
            pass
