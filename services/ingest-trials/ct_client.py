"""
ClinicalTrials.gov API v2 Client
==================================
Free API, no key required. Returns active clinical trials with:
  - Phase, status, sponsor, conditions
  - Primary/study completion dates (catalyst timing)
  - Intervention details (drug names)

Rate limit: be polite, ~3 req/sec max.
Docs: https://clinicaltrials.gov/data-api/api
"""
import logging
import httpx
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"

# Fields we need for catalyst detection
FIELDS = [
    "NCTId",
    "BriefTitle",
    "OfficialTitle",
    "OverallStatus",
    "Phase",
    "StartDate",
    "PrimaryCompletionDate",
    "CompletionDate",
    "StudyFirstPostDate",
    "LastUpdatePostDate",
    "LeadSponsorName",
    "CollaboratorName",
    "Condition",
    "InterventionName",
    "InterventionType",
    "StudyType",
    "EnrollmentCount",
    "DesignPrimaryPurpose",
    "ResultsFirstPostDate",
]

# Phases that matter for binary catalysts
CATALYST_PHASES = ["PHASE2", "PHASE3", "PHASE2/PHASE3"]

# Statuses that indicate an active/upcoming catalyst
ACTIVE_STATUSES = [
    "RECRUITING",
    "ACTIVE_NOT_RECRUITING",
    "ENROLLING_BY_INVITATION",
    "COMPLETED",  # Results may be pending
]


def _safe_get(d: dict, *keys, default=None):
    """Safely traverse nested dict."""
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
    """Parse ClinicalTrials.gov date formats."""
    if not date_str:
        return None
    for fmt in ["%Y-%m-%d", "%Y-%m", "%B %d, %Y", "%B %Y"]:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _extract_study(study_data: dict) -> Dict[str, Any]:
    """Extract relevant fields from a CT.gov v2 study response."""
    proto = study_data.get("protocolSection", {})
    ident = proto.get("identificationModule", {})
    status_mod = proto.get("statusModule", {})
    sponsor_mod = proto.get("sponsorCollaboratorsModule", {})
    design_mod = proto.get("designModule", {})
    conditions_mod = proto.get("conditionsModule", {})
    interventions_mod = proto.get("armsInterventionsModule", {})
    desc_mod = proto.get("descriptionModule", {})

    # Sponsor info
    lead_sponsor = _safe_get(sponsor_mod, "leadSponsor", "name", default="")
    sponsor_class = _safe_get(sponsor_mod, "leadSponsor", "class", default="")
    collaborators = [
        c.get("name", "") for c in sponsor_mod.get("collaborators", [])
    ]

    # Phase
    phases = design_mod.get("phases", [])
    phase_str = "/".join(phases) if phases else ""

    # Dates
    start_date = _safe_get(status_mod, "startDateStruct", "date")
    primary_completion = _safe_get(status_mod, "primaryCompletionDateStruct", "date")
    completion = _safe_get(status_mod, "completionDateStruct", "date")
    results_date = _safe_get(status_mod, "resultsFirstPostDateStruct", "date")

    # Conditions
    conditions = conditions_mod.get("conditions", [])

    # Interventions
    interventions = []
    for interv in interventions_mod.get("interventions", []):
        interventions.append({
            "name": interv.get("name", ""),
            "type": interv.get("type", ""),
            "description": interv.get("description", "")[:200] if interv.get("description") else "",
        })

    # Enrollment
    enrollment = _safe_get(design_mod, "enrollmentInfo", "count")

    return {
        "nct_id": ident.get("nctId", ""),
        "title": ident.get("briefTitle", ""),
        "official_title": ident.get("officialTitle", ""),
        "status": status_mod.get("overallStatus", ""),
        "phase": phase_str,
        "lead_sponsor": lead_sponsor,
        "sponsor_class": sponsor_class,  # INDUSTRY / NIH / OTHER
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


async def search_trials(
    sponsor: Optional[str] = None,
    condition: Optional[str] = None,
    intervention: Optional[str] = None,
    phases: Optional[List[str]] = None,
    statuses: Optional[List[str]] = None,
    page_size: int = 50,
    max_pages: int = 5,
) -> List[Dict[str, Any]]:
    """
    Search ClinicalTrials.gov for trials matching criteria.
    Returns parsed study records.
    """
    if phases is None:
        phases = CATALYST_PHASES
    if statuses is None:
        statuses = ACTIVE_STATUSES

    params = {
        "format": "json",
        "pageSize": min(page_size, 100),
    }

    # Build filters as separate params (CT.gov v2 API syntax)
    if phases:
        params["filter.phase"] = ",".join(phases)
    if statuses:
        params["filter.overallStatus"] = ",".join(statuses)
    if sponsor:
        params["query.spons"] = sponsor
    if condition:
        params["query.cond"] = condition
    if intervention:
        params["query.intr"] = intervention

    all_studies = []

    async with httpx.AsyncClient(timeout=30) as client:
        for page in range(max_pages):
            if page > 0:
                params["pageToken"] = next_token

            try:
                resp = await client.get(BASE_URL, params=params)
                if resp.status_code != 200:
                    logger.error(f"CT.gov API returned {resp.status_code}: {resp.text[:200]}")
                    break

                data = resp.json()
                studies = data.get("studies", [])

                for study in studies:
                    parsed = _extract_study(study)
                    all_studies.append(parsed)

                next_token = data.get("nextPageToken")
                if not next_token:
                    break

            except Exception as e:
                logger.error(f"CT.gov search failed: {e}")
                break

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
