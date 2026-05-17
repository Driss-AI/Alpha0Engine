"""USPTO PatentsView API Client — https://patentsview.org/apis/api-endpoints/patents"""
import os, logging, requests
from datetime import datetime
from typing import List, Dict, Any

log = logging.getLogger(__name__)
PATENTSVIEW_BASE = "https://api.patentsview.org"


class UsptoClient:
    def __init__(self):
        self.session = requests.Session()
        api_key = os.environ.get("PATENTSVIEW_API_KEY", "")
        if api_key:
            self.session.headers["X-Api-Key"] = api_key
        self.session.headers["Content-Type"] = "application/json"

    def get_patents(self, date_from: str, date_to: str, query_type: str = "grant") -> List[Dict[str, Any]]:
        endpoint = f"{PATENTSVIEW_BASE}/patents/query" if query_type == "grant" else f"{PATENTSVIEW_BASE}/applications/query"
        date_field = "patent_date" if query_type == "grant" else "app_date"
        payload = {
            "q": {"_and": [{"_gte": {date_field: date_from}}, {"_lte": {date_field: date_to}}]},
            "f": ["patent_id","patent_title","patent_date","patent_type","assignee_organization","assignee_id","inventor_last_name","inventor_first_name","cpc_group_id","cited_patent_count"],
            "o": {"per_page": 1000, "page": 1},
        }
        all_patents, page = [], 1
        while True:
            payload["o"]["page"] = page
            try:
                resp = self.session.post(endpoint, json=payload, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                log.error(f"PatentsView error page {page}: {e}")
                break
            patents = data.get("patents") or data.get("applications") or []
            all_patents.extend(patents)
            total = data.get("total_patent_count") or data.get("total_count") or 0
            if len(all_patents) >= total or not patents:
                break
            page += 1
        return all_patents

    def process_patent(self, patent: Dict[str, Any]) -> None:
        try:
            import asyncio
            from shared.clients.postgres import AsyncSessionLocal
            from shared.schemas.signals import Signal
            assignee = patent.get("assignee_organization", "")
            if not assignee:
                return
            signal = Signal(
                entity_id="UNRESOLVED",
                signal_type="patent_grant" if patent.get("patent_date") else "patent_filing",
                signal_date=datetime.strptime(patent.get("patent_date") or datetime.utcnow().strftime("%Y-%m-%d"), "%Y-%m-%d"),
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
