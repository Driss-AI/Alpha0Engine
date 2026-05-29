"""
Prometheus-compatible /metrics endpoint.
Exposes counters and gauges for pipeline monitoring and alerting.
"""
from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlmodel import select, func, col
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.clients.postgres import get_session
from shared.schemas.signals import Signal
from shared.schemas.ingestion_run import IngestionRun
from shared.schemas.equity_screen import EquityScreen
from shared.schemas.score_snapshot import ScoreSnapshot
from shared.schemas.brain_opportunity import BrainOpportunity
from shared.schemas.entities import Entity

router = APIRouter(tags=["Metrics"])


def _prom_line(name: str, value, help_text: str = "", type_: str = "gauge") -> str:
    lines = []
    if help_text:
        lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} {type_}")
    lines.append(f"{name} {value}")
    return "\n".join(lines)


def _prom_labeled(name: str, labels: dict, value) -> str:
    label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
    return f"{name}{{{label_str}}} {value}"


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics(session: AsyncSession = Depends(get_session)):
    """Prometheus exposition format metrics."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = date.today()
    week_ago = today - timedelta(days=7)

    lines = []

    # Entity counts
    entity_count = (await session.exec(
        select(func.count()).select_from(Entity)
    )).one()
    lines.append(_prom_line(
        "alpha0_entities_total", entity_count,
        "Total tracked entities", "gauge"
    ))

    # Signals ingested (total and last 7 days)
    signal_total = (await session.exec(
        select(func.count()).select_from(Signal)
    )).one()
    lines.append(_prom_line(
        "alpha0_signals_total", signal_total,
        "Total signals ingested", "counter"
    ))

    signal_week = (await session.exec(
        select(func.count()).select_from(Signal)
        .where(col(Signal.created_at) >= datetime.combine(week_ago, datetime.min.time()))
    )).one()
    lines.append(_prom_line(
        "alpha0_signals_last_7d", signal_week,
        "Signals ingested in last 7 days", "gauge"
    ))

    # Screened entities by tier
    tier_counts = (await session.exec(
        select(EquityScreen.conviction_tier, func.count())
        .group_by(EquityScreen.conviction_tier)
    )).all()
    lines.append("# HELP alpha0_screened_by_tier Screened entities per conviction tier")
    lines.append("# TYPE alpha0_screened_by_tier gauge")
    for tier, count in tier_counts:
        lines.append(_prom_labeled("alpha0_screened_by_tier", {"tier": tier}, count))

    # Brain picks (daily)
    brain_today = (await session.exec(
        select(func.count()).select_from(BrainOpportunity)
        .where(col(BrainOpportunity.created_at) >= datetime.combine(today, datetime.min.time()))
    )).one()
    lines.append(_prom_line(
        "alpha0_brain_picks_today", brain_today,
        "Brain picks generated today", "gauge"
    ))

    # Ingestion runs — last 24h errors
    recent_runs = (await session.exec(
        select(IngestionRun)
        .where(col(IngestionRun.started_at) >= now - timedelta(hours=24))
    )).all()

    run_errors = sum(r.errors or 0 for r in recent_runs)
    run_count = len(recent_runs)
    lines.append(_prom_line(
        "alpha0_ingestion_runs_24h", run_count,
        "Ingestion runs in last 24 hours", "gauge"
    ))
    lines.append(_prom_line(
        "alpha0_ingestion_errors_24h", run_errors,
        "Ingestion errors in last 24 hours", "gauge"
    ))

    # Per-service ingestion status
    lines.append("# HELP alpha0_ingestion_last_run_status Last run status per service (1=success, 0=failed)")
    lines.append("# TYPE alpha0_ingestion_last_run_status gauge")
    services_seen = set()
    for run in sorted(recent_runs, key=lambda r: r.started_at or now, reverse=True):
        if run.service_name in services_seen:
            continue
        services_seen.add(run.service_name)
        status_val = 1 if run.status == "completed" else 0
        lines.append(_prom_labeled(
            "alpha0_ingestion_last_run_status",
            {"service": run.service_name},
            status_val,
        ))

    # Score snapshots today
    snap_today = (await session.exec(
        select(func.count()).select_from(ScoreSnapshot)
        .where(ScoreSnapshot.snapshot_date == today)
    )).one()
    lines.append(_prom_line(
        "alpha0_score_snapshots_today", snap_today,
        "Score snapshots written today", "gauge"
    ))

    lines.append("")
    return "\n".join(lines)
