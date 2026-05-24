"""
Pipeline Health Router — system reliability dashboard
Shows which data pipelines are running, stale, or broken.
"""
from fastapi import APIRouter
from shared.clients.heartbeat import check_pipeline_health

router = APIRouter(tags=["Health"])


@router.get("/pipelines")
async def get_pipeline_health():
    """
    Pipeline health status for all data feeds.
    Status: ok / warning / stale / error / never_run
    """
    statuses = await check_pipeline_health()

    # Summary counts
    total = len(statuses)
    ok = sum(1 for s in statuses if s["status"] == "ok")
    warning = sum(1 for s in statuses if s["status"] == "warning")
    stale = sum(1 for s in statuses if s["status"] == "stale")
    error = sum(1 for s in statuses if s["status"] == "error")

    # Overall system health
    if error > 0:
        system_status = "degraded"
    elif stale > 0:
        system_status = "warning"
    elif total == 0:
        system_status = "no_data"
    else:
        system_status = "healthy"

    return {
        "system_status": system_status,
        "total_pipelines": total,
        "ok": ok,
        "warning": warning,
        "stale": stale,
        "error": error,
        "pipelines": sorted(statuses, key=lambda s: s["pipeline"]),
    }
