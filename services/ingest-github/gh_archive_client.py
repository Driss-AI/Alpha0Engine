"""
GitHub Archive Client — https://www.gharchive.org/
URL format: https://data.gharchive.org/{YYYY-MM-DD-H}.json.gz
"""
import gzip, json, logging, requests
from datetime import datetime
from typing import List, Dict, Any

log = logging.getLogger(__name__)
GH_ARCHIVE_BASE = "https://data.gharchive.org"
TRACKED_EVENT_TYPES = {"PushEvent","WatchEvent","ForkEvent","CreateEvent","MemberEvent","ReleaseEvent"}


class GitHubArchiveClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "Alpha0Engine/1.0"

    def fetch_hour(self, dt: datetime) -> List[Dict[str, Any]]:
        url = f"{GH_ARCHIVE_BASE}/{dt.strftime('%Y-%m-%d')}-{dt.hour}.json.gz"
        log.info(f"Downloading: {url}")
        try:
            resp = self.session.get(url, timeout=120, stream=True)
            resp.raise_for_status()
            decompressed = gzip.decompress(resp.content).decode("utf-8")
            events = []
            for line in decompressed.splitlines():
                line = line.strip()
                if not line: continue
                try: events.append(json.loads(line))
                except json.JSONDecodeError: continue
            return events
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                log.warning("File not yet available")
            else:
                log.error(f"HTTP error: {e}")
            return []
        except Exception as e:
            log.error(f"Fetch error: {e}")
            return []

    def filter_relevant(self, events: List[Dict], tracked_orgs: Dict[str, str]) -> List[Dict]:
        orgs_lower = {k.lower() for k in tracked_orgs}
        relevant = []
        for event in events:
            if event.get("type","") not in TRACKED_EVENT_TYPES: continue
            repo = event.get("repo",{}).get("name","")
            org = repo.split("/")[0].lower() if "/" in repo else ""
            if org in orgs_lower:
                event["_tracked_org"] = org
                relevant.append(event)
        return relevant

    def process_event(self, event: Dict, tracked_orgs: Dict[str, str]) -> None:
        try:
            import asyncio
            from shared.clients.postgres import AsyncSessionLocal
            from shared.schemas.signals import Signal
            org = event.get("_tracked_org","")
            signal = Signal(
                entity_id="UNRESOLVED",
                signal_type=self._type(event["type"]),
                signal_date=datetime.strptime(event.get("created_at", datetime.utcnow().isoformat())[:19], "%Y-%m-%dT%H:%M:%S"),
                value=self._value(event),
                raw_data={"event_id": event.get("id"), "type": event.get("type"),
                          "actor": event.get("actor",{}).get("login"), "repo": event.get("repo",{}).get("name"), "org": org},
                source="github", source_id=event.get("id"),
            )
            async def _w():
                async with AsyncSessionLocal() as s:
                    s.add(signal)
                    await s.commit()
            asyncio.get_event_loop().run_until_complete(_w())
        except Exception as e:
            log.error(f"Event write failed: {e}")

    @staticmethod
    def _type(t): return {"PushEvent":"github_commit","WatchEvent":"github_star","ForkEvent":"github_star","MemberEvent":"job_posting","ReleaseEvent":"github_commit","CreateEvent":"github_commit"}.get(t,"github_commit")

    @staticmethod
    def _value(event):
        t = event.get("type","")
        p = event.get("payload",{})
        if t == "PushEvent": return min(0.5 + len(p.get("commits",[])) * 0.05, 1.0)
        if t == "WatchEvent": return 0.3
        if t == "ForkEvent": return 0.4
        if t == "MemberEvent": return 0.7
        if t == "ReleaseEvent": return 0.8
        return 0.2


    def _publish_to_stream(self, signal_data):
        """Publish to Redis stream for entity resolver."""
        try:
            import asyncio
            from shared.clients.redis_client import publish_signal
            asyncio.get_event_loop().run_until_complete(publish_signal(signal_data))
        except Exception as e:
            log.error(f"Redis publish failed: {e}")
