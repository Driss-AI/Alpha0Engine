"""
USPTO Patent Ingest — uses multiple free sources, no API key required.

Sources (in priority order):
1. PatentSearch API (if key set) — best structured data
2. USPTO bulk data RSS feed — free, no auth, always available
3. Google Patents public dataset — free via BigQuery

The RSS feed at https://www.uspto.gov/rss gives us weekly patent grants.
"""
import os, logging, requests, re
from datetime import datetime, timedelta
from typing import List, Dict, Any

log = logging.getLogger(__name__)

PATENTSEARCH_BASE = "https://search.patentsview.org/api/v1"
USPTO_RSS_GRANTS = "https://www.uspto.gov/rss/feeds/patents-issued.xml"
USPTO_RSS_APPS = "https://www.uspto.gov/rss/feeds/patent-applications.xml"


class UsptoClient:
    def __init__(self):
        self.api_key = os.environ.get("PATENTSVIEW_API_KEY", "")
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "Alpha0Engine/1.0"
        if self.api_key:
            self.session.headers["X-Api-Key"] = self.api_key

    def get_patents(self, date_from: str, date_to: str, query_type: str = "grant") -> List[Dict[str, Any]]:
        # Try PatentSearch API if key is available
        if self.api_key:
            results = self._search_patentsearch(date_from, date_to, query_type)
            if results:
                return results

        # Fallback: USPTO RSS feeds (always free, no auth)
        return self._parse_rss_feed(query_type)

    def _search_patentsearch(self, date_from, date_to, query_type):
        endpoint = f"{PATENTSEARCH_BASE}/patent/"
        q = '{{"_and":[{{"_gte":{{"patent_date":"{0}"}}}},{{"_lte":{{"patent_date":"{1}"}}}}]}}'.format(date_from, date_to)
        try:
            resp = self.session.get(endpoint, params={
                "q": q,
                "f": "patent_id,patent_title,patent_date,patent_type,assignees.assignee_organization",
                "o": '{"per_page":100,"page":1}',
            }, timeout=30)
            if resp.status_code in (401, 403, 410):
                log.warning(f"PatentSearch API returned {resp.status_code}")
                return []
            resp.raise_for_status()
            return resp.json().get("patents", [])
        except Exception as e:
            log.error(f"PatentSearch error: {e}")
            return []

    def _parse_rss_feed(self, query_type: str) -> List[Dict[str, Any]]:
        """Parse USPTO RSS feed for recent patents. Free, no auth."""
        url = USPTO_RSS_GRANTS if query_type == "grant" else USPTO_RSS_APPS
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code != 200:
                log.warning(f"USPTO RSS returned {resp.status_code}")
                return []

            content = resp.text
            patents = []

            # Parse RSS XML items
            items = re.findall(r"<item>(.*?)</item>", content, re.DOTALL)
            for item in items[:100]:
                title = re.search(r"<title>(.*?)</title>", item)
                link = re.search(r"<link>(.*?)</link>", item)
                pub_date = re.search(r"<pubDate>(.*?)</pubDate>", item)
                desc = re.search(r"<description>(.*?)</description>", item, re.DOTALL)

                patent_title = title.group(1).strip() if title else ""
                patent_url = link.group(1).strip() if link else ""

                # Extract patent number from title or link
                pat_num = re.search(r"(\d{7,})", patent_url or patent_title)
                patent_id = pat_num.group(1) if pat_num else ""

                # Extract assignee from description if available
                assignee = ""
                if desc:
                    desc_text = desc.group(1)
                    assignee_match = re.search(r"(?:assignee|applicant)[:\s]*([^<;]+)", desc_text, re.IGNORECASE)
                    if assignee_match:
                        assignee = assignee_match.group(1).strip()

                # Parse date
                patent_date = datetime.utcnow().strftime("%Y-%m-%d")
                if pub_date:
                    try:
                        from email.utils import parsedate_to_datetime
                        patent_date = parsedate_to_datetime(pub_date.group(1)).strftime("%Y-%m-%d")
                    except Exception:
                        pass

                if patent_title:
                    patents.append({
                        "patent_id": patent_id,
                        "patent_title": patent_title,
                        "patent_date": patent_date,
                        "patent_type": query_type,
                        "assignee_organization": assignee,
                        "patent_url": patent_url,
                    })

            log.info(f"USPTO RSS parsed {len(patents)} {query_type}s")
            return patents

        except Exception as e:
            log.error(f"USPTO RSS parse error: {e}")
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

            # Skip if no title and no assignee (empty entry)
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
            log.error(f"Patent signal write failed: {e}")
