"""
ClinicalTrials.gov API v2 Client
==================================
Free API, no key required. Returns active clinical trials with:
  - Phase, status, sponsor, conditions
  - Primary/study completion dates (catalyst timing)
  - Intervention details (drug names)

Phase filtering uses the v2 `aggFilters` parameter (`phase:2 3`) — the older
`filter.phase` name is NOT a valid v2 parameter and returns HTTP 400. We also
filter phase client-side as a safety net, so a filter-syntax drift degrades to
"fetch more, keep the right ones" instead of returning nothing.

Rate limit: the public endpoint 429s aggressively from cloud IPs, so every
request goes through a backoff-retry that honors Retry-After.
Docs: https://clinicaltrials.gov/data-api/api
"""
import asyncio
import logging
import httpx
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"

# Phases that matter for binary catalysts
CATALYST_PHASES = ["PHASE2", "PHASE3", "PHASE2/PHASE3"]

# Statuses that indicate an active/upcoming catalyst
ACTIVE_STATUSES = [
    "RECRUITING",
    "ACTIVE_NOT_RECRUITING",
    "ENROLLING_BY_INVITATION",
    "COMPLETED",  # Results may be pending
]

# v2 aggFilters phase codes: 0=Early P1, 1=P1, 2=P2, 3=P3, 4=P4
_PHASE_CODE = {"EARLY_PHASE1": "0", "PHASE1": "1", "PHASE2": "2", "PHASE3": "3", "PHASE4": "4"}

_MAX_RETRIES = 5


def _phase_codes(phases: List[str]) -> List[str]:
    """Map phase names (incl. combined 'PHASE2/PHASE3') to v2 aggFilter codes."""
    codes: List[str] = []
    for p in phases:
        for part in p.upper().split("/"):
            code = _PHASE_CODE.get(part.strip())
            if code and code not in codes:
                codes.append(code)
    return codes


def _phase_matches(phase_str: str, wanted: List[str]) -> bool:
    """Client-side guard: does a study's phase overlap the requested phases?"""
    if not wanted:
        return True
    have = {p.strip().upper() for p in (phase_str or "").split("/") if p.strip()}
    want = {p.strip().upper() for w in wanted for p in w.split("/")}
    return bool(have & want)


def _build_params(
    *,
    sponsor: Optional[str],
    condition: Optional[str],
    intervention: Optional[str],
    phases: List[str],
    statuses: List[str],
    page_size: int,
) -> Dict[str, str]:
    """Assemble v2 query params. Never emits the invalid `filter.phase`."""
    params: Dict[str, str] = {"format": "json", "pageSize": str(min(page_size, 100))}
    codes = _phase_codes(phases)
    if codes:
        params["aggFilters"] = f"phase:{' '.join(codes)}"
    if statuses:
        params["filter.overallStatus"] = ",".join(statuses)
    if sponsor:
        params["query.spons"] = sponsor
    if condition:
        params["query.cond"] = condition
    if intervention:
        params["query.intr"] = intervention
    return params


def _safe_get(d: dict, *keys, default=None):
    current = d
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        elif isinstance(current, list) and current:
            current = current[0] if key == 0 else default
        else:
            return default
    return current if current is not None else default


def _parse_ct_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    for fmt in ["%Y-%m-%d", "%Y-%m", "%B %d, %Y", "%B %Y"]:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _extract_study(study_data: dict) -> Dict[str, Any]:
    proto = study_data.get("protocolSection", {})
    ident = proto.get("identificationModule", {})
    status_mod = proto.get("statusModule", {})
    sponsor_mod = proto.get("sponsorCollaboratorsModule", {})
    design_mod = proto.get("designModule", {})
    conditions_mod = proto.get("conditionsModule", {})
    interventions_mod = proto.get("armsInterventionsModule", {})

    lead_sponsor = _safe_get(sponsor_mod, "leadSponsor", "name", default="")
    sponsor_class = _safe_get(sponsor_mod, "leadSponsor", "class", default="")
    collaborators = [c.get("name", "") for c in sponsor_mod.get("collaborators", [])]

    phases = design_mod.get("phases", [])
    phase_str = "/".join(phases) if phases else ""

    start_date = _safe_get(status_mod, "startDateStruct", "date")
    primary_completion = _safe_get(status_mod, "primaryCompletionDateStruct", "date")
    completion = _safe_get(status_mod, "completionDateStruct", "date")
    results_date = _safe_get(status_mod, "resultsFirstPostDateStruct", "date")

    conditions = conditions_mod.get("conditions", [])
    interventions = []
    for interv in interventions_mod.get("interventions", []):
        interventions.append({
            "name": interv.get("name", ""),
            "type": interv.get("type", ""),
            "description": interv.get("description", "")[:200] if interv.get("description") else "",
        })
    enrollment = _safe_get(design_mod, "enrollmentInfo", "count")

    return {
        "nct_id": ident.get("nctId", ""),
        "title": ident.get("briefTitle", ""),
        "official_title": ident.get("officialTitle", ""),
        "status": status_mod.get("overallStatus", ""),
        "phase": phase_str,
        "lead_sponsor": lead_sponsor,
        "sponsor_class": sponsor_class,
        "collaborators": collaborators,
        "conditions": conditions,
        "interventions": interventions,
        "enrollment": enrollment,
        "start_date": start_date,
        "primary_completion_date": primary_completion,
        "completion_date": completion,
        "results_date": results_date,
        "start_dt": _parse_ct_date(start_date),
        "primary_completion_dt": _parse_ct_date(primary_completion),
        "completion_dt": _parse_ct_date(completion),
    }


async def _get_with_retry(
    client: httpx.AsyncClient, params: Dict[str, str],
) -> Optional[httpx.Response]:
    """GET with 429 backoff (honors Retry-After). Returns None if it never got 2xx/4xx≠429."""
    delay = 2.0
    for attempt in range(_MAX_RETRIES):
        try:
            resp = await client.get(BASE_URL, params=params)
        except Exception as e:
            logger.error(f"CT.gov request error: {e}")
            return None
        if resp.status_code == 429:
            wait = delay
            ra = resp.headers.get("retry-after")
            if ra:
                try:
                    wait = float(ra)
                except ValueError:
                    pass
            logger.warning(f"CT.gov 429 — backing off {wait:.0f}s (attempt {attempt + 1})")
            await asyncio.sleep(wait)
            delay = min(delay * 2, 60)
            continue
        return resp
    return None


async def search_trials(
    sponsor: Optional[str] = None,
    condition: Optional[str] = None,
    intervention: Optional[str] = None,
    phases: Optional[List[str]] = None,
    statuses: Optional[List[str]] = None,
    page_size: int = 50,
    max_pages: int = 5,
) -> List[Dict[str, Any]]:
    """Search ClinicalTrials.gov (v2) for trials matching criteria."""
    if phases is None:
        phases = CATALYST_PHASES
    if statuses is None:
        statuses = ACTIVE_STATUSES

    params = _build_params(
        sponsor=sponsor, condition=condition, intervention=intervention,
        phases=phases, statuses=statuses, page_size=page_size,
    )

    all_studies: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for page in range(max_pages):
            resp = await _get_with_retry(client, params)
            if resp is None:
                break
            if resp.status_code != 200:
                logger.error(f"CT.gov API returned {resp.status_code}: {resp.text[:200]}")
                break

            data = resp.json()
            for study in data.get("studies", []):
                parsed = _extract_study(study)
                if _phase_matches(parsed["phase"], phases):  # client-side guard
                    all_studies.append(parsed)

            next_token = data.get("nextPageToken")
            if not next_token:
                break
            params["pageToken"] = next_token

    return all_studies


async def search_by_sponsor(sponsor_name: str) -> List[Dict[str, Any]]:
    """Search for Phase 2/3 trials by sponsor company name."""
    return await search_trials(sponsor=sponsor_name)


async def search_active_phase3() -> List[Dict[str, Any]]:
    """Get all active Phase 3 trials (industry-sponsored)."""
    return await search_trials(
        phases=["PHASE3"],
        statuses=["RECRUITING", "ACTIVE_NOT_RECRUITING", "COMPLETED"],
        page_size=100,
        max_pages=20,
    )


async def get_trial_by_nct(nct_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single trial by NCT ID."""
    url = f"{BASE_URL}/{nct_id}"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(url, params={"format": "json"})
            if resp.status_code == 200:
                return _extract_study(resp.json())
            return None
        except Exception as e:
            logger.error(f"CT.gov fetch failed for {nct_id}: {e}")
            return None
