"""
USPTO PatentSearch API Client
Legacy API discontinued May 2025. New API at search.patentsview.org.
Migrated to USPTO Open Data Portal March 2026.
Falls back gracefully if no API key.
"""
import os, logging, requests
from datetime import datetime
from typing import List, Dict, Any

log = logging.getLogger(__name__)

PATENTSEARCH_BASE = "https://search.patentsview.org/api/v1"


class UsptoClient:
    def __init__(self):
        self.api_key = os.environ.get("PATENTSVIEW_API_KEY", "")
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "Alpha0Engine/1.0"
        if self.api_key:
            self.session.headers["X-Api-Key"] = self.api_key

    def get_patents(self, date_from: str, date_to: str, query_type: str = "grant") -> List[Dict[str, Any]]:
        if self.api_key:
            return self._search_new_api(date_from, date_to, query_type)

        log.warning(
            "No PatentsView API key. Get a free key: "
            "https://patentsview.org/apis — request PatentSearch API key. "
            "Set PATENTSVIEW_API_KEY in Railway env vars. "
            "Patent ingest will be inactive until key is set."
        )
        return []

    def _search_new_api(self, date_from, date_to, query_type):
        endpoint = f"{PATENTSEARCH_BASE}/patent/"
        q = '{{"_and":[{{"_gte":{{"patent_date":"{0}"}}}},{{"_lte":{{"patent_date":"{1}"}}}}]}}'.format(date_from, date_to)
        params = {
            "q": q,
            "f": "patent_id,patent_title,patent_date,patent_type,assignees.assignee_organization",
        }
        all_patents = []
        page = 1
        while True:
            params["o"] = '{{"per_page":100,"page":{0}}}'.format(page)
            try:
                resp = self.session.get(endpoint, params=params, timeout=30)
                if resp.status_code == 410:
                    log.warning("PatentSearch API returned 410 — may have migrated to data.uspto.gov")
                    return all_patents
                if resp.status_code == 401:
                    log.error("PatentSearch API key invalid or expired. Request new key.")
                    return all_patents
                resp.raise_for_status()
                data = resp.json()
                patents = data.get("patents", [])
                all_patents.extend(patents)
                total = data.get("total_patent_count", 0)
                if len(all_patents) >= total or not patents:
                    break
                page += 1
            except Exception as e:
                log.error(f"PatentSearch API error page {page}: {e}")
                break
        return all_patents

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
            if not assignee:
                return
            signal = Signal(
                entity_id="UNRESOLVED",
                signal_type="patent_grant" if patent.get("patent_date") else "patent_filing",
                signal_date=datetime.strptime(
                    patent.get("patent_date") or datetime.utcnow().strftime("%Y-%m-%d"), "%Y-%m-%d"
                ),
                value=0.6, raw_data=patent, source="uspto",
                source_id=patent.get("patent_id"), notes=f"Assignee: {assignee}",
            )
            async def _w():
                async with AsyncSessionLocal() as s:
                    s.add(signal)
                    await s.commit()
            asyncio.get_event_loop().run_until_complete(_w())
        except Exception as e:
            log.error(f"Patent signal write failed: {e}")
