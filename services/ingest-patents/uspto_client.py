"""
USPTO Patent Ingest
Old RSS decommissioned Feb 27, 2026. New approach:
1. PatentSearch API (if key set) — best
2. USPTO Open Data Portal bulk downloads
3. FreePatentsOnline RSS (third-party, always free)
"""
import os, logging, requests, re
from datetime import datetime
from typing import List, Dict, Any

log = logging.getLogger(__name__)


class UsptoClient:
    def __init__(self):
        self.api_key = os.environ.get("PATENTSVIEW_API_KEY", "")
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "Alpha0Engine/1.0"
        if self.api_key:
            self.session.headers["X-Api-Key"] = self.api_key

    def get_patents(self, date_from: str, date_to: str, query_type: str = "grant") -> List[Dict[str, Any]]:
        if self.api_key:
            results = self._patentsearch_api(date_from, date_to)
            if results:
                return results

        # FreePatentsOnline RSS — third-party, always free, no auth
        return self._freepatents_rss(query_type)

    def _patentsearch_api(self, date_from, date_to):
        try:
            q = '{{"_and":[{{"_gte":{{"patent_date":"{0}"}}}},{{"_lte":{{"patent_date":"{1}"}}}}]}}'.format(date_from, date_to)
            resp = self.session.get(
                "https://search.patentsview.org/api/v1/patent/",
                params={"q": q, "f": "patent_id,patent_title,patent_date,assignees.assignee_organization", "o": '{"per_page":100}'},
                timeout=30
            )
            if resp.status_code in (401, 403, 410):
                return []
            resp.raise_for_status()
            return resp.json().get("patents", [])
        except Exception as e:
            log.debug(f"PatentSearch API: {e}")
            return []

    def _freepatents_rss(self, query_type: str) -> List[Dict[str, Any]]:
        """Parse FreePatentsOnline RSS for recent patents."""
        urls = [
            "https://www.freepatentsonline.com/rssfeed.html?type=patent&sort=date",
            "https://www.freepatentsonline.com/rss20.xml",
        ]
        for url in urls:
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code != 200:
                    continue
                content = resp.text

                patents = []
                items = re.findall(r"<item>(.*?)</item>", content, re.DOTALL)
                for item in items[:100]:
                    title = re.search(r"<title>(.*?)</title>", item)
                    link = re.search(r"<link>(.*?)</link>", item)
                    desc = re.search(r"<description>(.*?)</description>", item, re.DOTALL)

                    patent_title = title.group(1).strip() if title else ""
                    if not patent_title:
                        continue

                    patent_url = link.group(1).strip() if link else ""
                    pat_num = re.search(r"(\d{7,})", patent_url or patent_title)
                    patent_id = pat_num.group(1) if pat_num else ""

                    assignee = ""
                    if desc:
                        a = re.search(r"(?:assignee|applicant)[:\s]*([^<;,]+)", desc.group(1), re.IGNORECASE)
                        if a:
                            assignee = a.group(1).strip()

                    patents.append({
                        "patent_id": patent_id,
                        "patent_title": patent_title,
                        "patent_date": datetime.utcnow().strftime("%Y-%m-%d"),
                        "patent_type": query_type,
                        "assignee_organization": assignee,
                    })

                if patents:
                    log.info(f"FreePatentsOnline: {len(patents)} patents parsed")
                    return patents
            except Exception as e:
                log.debug(f"FreePatents RSS error: {e}")

        log.info("No patent data available without API key. Set PATENTSVIEW_API_KEY for full patent coverage.")
        return []

    def process_patent(self, patent: Dict[str, Any]) -> None:
        try:
            import asyncio
            from shared.clients.postgres import AsyncSessionLocal
            from shared.schemas.signals import Signal

            assignee = ""
            if isinstance(patent.get("assignees"), list) and patent["assignees"]:
                assignee = patent["assignees"][0].get("assignee_organization", "")
            else:
                assignee = patent.get("assignee_organization", "")

            if not assignee and not patent.get("patent_title"):
                return

            signal = Signal(
                entity_id="UNRESOLVED",
                signal_type="patent_grant" if patent.get("patent_type") == "grant" else "patent_filing",
                signal_date=datetime.strptime(
                    patent.get("patent_date") or datetime.utcnow().strftime("%Y-%m-%d"), "%Y-%m-%d"
                ),
                value=0.6, raw_data=patent, source="uspto",
                source_id=patent.get("patent_id"),
                notes=f"Assignee: {assignee}" if assignee else patent.get("patent_title", "")[:100],
            )
            async def _w():
                async with AsyncSessionLocal() as s:
                    s.add(signal)
                    await s.commit()
            asyncio.get_event_loop().run_until_complete(_w())
        except Exception as e:
            log.error(f"Patent write failed: {e}")
