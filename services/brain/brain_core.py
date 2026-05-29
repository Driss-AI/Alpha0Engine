"""
Brain Core — Orchestrator
==========================
Runs the full Brain pipeline:

  1. Scan candidates (candidate_scanner)
  2. Collect evidence bundles (evidence_collector)
  3. Analyze each via Claude (brain_analyst)
  4. Verify citations (verification)
  5. Apply threshold gate
  6. Persist opportunities + narratives to DB

Designed to run as a daily cron job (Sprint 4) or ad-hoc.
"""
import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
_HERE = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(_HERE, ".env"), override=True)

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from shared.clients.postgres import AsyncSessionLocal, create_db_and_tables
from shared.schemas.brain_opportunity import BrainOpportunity
from shared.schemas.brain_narrative import BrainNarrative
from shared.schemas.daily_prices import DailyPrice

from candidate_scanner import scan_candidates
from evidence_collector import collect_evidence_batch
from brain_analyst import analyze_candidate
from verification import verify_analysis, passes_threshold

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(name)s | %(message)s",
)
logger = logging.getLogger("brain.core")

ANALYSIS_DELAY_SECONDS = 1.5  # rate-limit between Claude calls


def _map_time_horizon_to_expiry(horizon: Optional[str]) -> Optional[datetime]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if horizon == "short":
        return now + timedelta(days=30)
    elif horizon == "medium":
        return now + timedelta(days=90)
    elif horizon == "long":
        return now + timedelta(days=180)
    return now + timedelta(days=60)


async def _get_latest_price(session: AsyncSession, ticker: str) -> Optional[float]:
    result = await session.exec(
        select(DailyPrice.close)
        .where(DailyPrice.ticker == ticker, DailyPrice.close.isnot(None))
        .order_by(DailyPrice.trade_date.desc())
        .limit(1)
    )
    return result.first()


async def _persist_opportunity(
    session: AsyncSession,
    candidate: Dict[str, Any],
    analysis: Dict[str, Any],
    evidence: Dict[str, Any],
) -> BrainOpportunity:
    """Save a verified opportunity to the database."""
    entity = evidence.get("entity", {})
    screener = evidence.get("screener", {}) or {}
    verification = analysis.get("_verification", {})

    pick_price = await _get_latest_price(session, candidate.get("ticker", ""))

    opp = BrainOpportunity(
        entity_id=candidate["entity_id"],
        ticker=candidate.get("ticker"),
        company_name=candidate.get("company_name"),
        sector=entity.get("sector"),
        market_cap_usd=screener.get("market_cap_usd"),
        thesis=analysis.get("thesis", ""),
        narrative=analysis.get("narrative", ""),
        thesis_type=analysis.get("thesis_type"),
        upside_scenario=analysis.get("upside_scenario"),
        downside_scenario=analysis.get("downside_scenario"),
        return_multiple=analysis.get("return_multiple"),
        conviction=analysis.get("conviction", "LOW"),
        confidence_score=analysis.get("confidence_score", 0.0),
        signal_count=verification.get("total_cited", 0),
        source_diversity=len(verification.get("source_types_cited", [])),
        lenses_active=analysis.get("evidence_quality", {}).get("lenses_active", 0),
        catalysts=analysis.get("key_catalysts", []),
        time_horizon=analysis.get("time_horizon"),
        key_signals=analysis.get("key_signals", []),
        evidence_sources=verification.get("source_types_cited", []),
        status="active",
        expires_at=_map_time_horizon_to_expiry(analysis.get("time_horizon")),
        price_at_pick=pick_price,
        price_latest=pick_price,
        return_pct=0.0,
        screening_notes=(
            f"Paths: {candidate.get('path_count', 1)} | "
            f"Priority: {candidate.get('priority', 0):.3f} | "
            f"Citations: {verification.get('total_cited', 0)} | "
            f"Coverage: {verification.get('citation_coverage', 0):.0%}"
        ),
    )

    session.add(opp)
    await session.flush()
    logger.info(f"  Persisted opportunity {opp.id} for {opp.ticker}")
    return opp


async def _persist_narrative(
    session: AsyncSession,
    candidate: Dict[str, Any],
    analysis: Dict[str, Any],
    evidence: Dict[str, Any],
) -> BrainNarrative:
    """Save or update the brain narrative for this entity."""
    entity_id = candidate["entity_id"]
    verification = analysis.get("_verification", {})

    # Check for existing narrative to bump version
    result = await session.exec(
        select(BrainNarrative)
        .where(BrainNarrative.entity_id == entity_id)
        .order_by(BrainNarrative.version.desc())
        .limit(1)
    )
    existing = result.first()
    next_version = (existing.version + 1) if existing else 1

    key_changes = []
    if existing:
        if existing.conviction_level != analysis.get("conviction", "HOLD"):
            key_changes.append({
                "field": "conviction",
                "old": existing.conviction_level,
                "new": analysis.get("conviction", "HOLD"),
            })

    evidence_bundle_map = {}
    for sig in analysis.get("key_signals", []):
        sid = sig.get("source_id", "")
        evidence_bundle_map[sid] = sig.get("summary", "")

    conviction_map = {
        "HIGH": "STRONG_BUY",
        "MEDIUM": "BUY",
        "LOW": "HOLD",
        "NONE": "HOLD",
    }

    narrative = BrainNarrative(
        entity_id=entity_id,
        ticker=candidate.get("ticker"),
        company_name=candidate.get("company_name"),
        narrative_text=analysis.get("narrative", ""),
        summary=analysis.get("thesis", ""),
        key_changes=key_changes,
        conviction_level=conviction_map.get(analysis.get("conviction", "LOW"), "HOLD"),
        risk_summary="; ".join(
            r.get("description", "") for r in analysis.get("risk_factors", [])
        ) or None,
        bull_case=analysis.get("upside_scenario"),
        bear_case=analysis.get("downside_scenario"),
        trigger="; ".join(candidate.get("reasons", [])),
        trigger_signal_ids=verification.get("cited_ids", []),
        evidence_bundle=evidence_bundle_map,
        source_count=len(verification.get("source_types_cited", [])),
        version=next_version,
    )

    session.add(narrative)
    await session.flush()
    logger.info(f"  Persisted narrative v{next_version} for {candidate.get('ticker')}")
    return narrative


async def run_brain(
    max_candidates: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Run the full Brain pipeline.

    Args:
        max_candidates: Cap the number of candidates to analyze (saves API cost).
        dry_run: If True, run analysis but don't persist to DB.

    Returns:
        Summary dict with counts and details.
    """
    await create_db_and_tables()

    stats = {
        "candidates_scanned": 0,
        "evidence_collected": 0,
        "analyzed": 0,
        "verified": 0,
        "threshold_passed": 0,
        "persisted": 0,
        "passed_tickers": [],
        "failed_tickers": [],
        "errors": [],
        "total_input_tokens": 0,
        "total_output_tokens": 0,
    }

    async with AsyncSessionLocal() as session:
        # ── Step 1: Scan ──────────────────────────────────────
        logger.info("=" * 60)
        logger.info("BRAIN PIPELINE — Step 1: Scanning candidates")
        logger.info("=" * 60)

        candidates = await scan_candidates(session)
        stats["candidates_scanned"] = len(candidates)

        if not candidates:
            logger.info("No candidates found. Brain has nothing to analyze today.")
            return stats

        if max_candidates:
            candidates = candidates[:max_candidates]
            logger.info(f"Capped to {max_candidates} candidates")

        # ── Step 2: Evidence ──────────────────────────────────
        logger.info("=" * 60)
        logger.info("BRAIN PIPELINE — Step 2: Collecting evidence")
        logger.info("=" * 60)

        evidence_batch = await collect_evidence_batch(session, candidates)
        stats["evidence_collected"] = len(evidence_batch)

        if not evidence_batch:
            logger.info("No candidates with sufficient evidence.")
            return stats

        # ── Step 3 + 4 + 5: Analyze, Verify, Threshold ───────
        logger.info("=" * 60)
        logger.info("BRAIN PIPELINE — Step 3: Analyzing via Claude")
        logger.info("=" * 60)

        for item in evidence_batch:
            candidate = item["candidate"]
            evidence = item["evidence"]
            ticker = candidate.get("ticker", "?")

            try:
                # Analyze
                analysis = await analyze_candidate(candidate, evidence)
                if not analysis:
                    stats["errors"].append(f"{ticker}: analysis failed")
                    continue
                stats["analyzed"] += 1

                usage = analysis.pop("_usage", {})
                stats["total_input_tokens"] += usage.get("input_tokens", 0)
                stats["total_output_tokens"] += usage.get("output_tokens", 0)

                # Verify
                analysis = verify_analysis(analysis, evidence)
                stats["verified"] += 1

                # Threshold gate
                passes, fail_reasons = passes_threshold(analysis, evidence)
                if not passes:
                    stats["failed_tickers"].append({
                        "ticker": ticker,
                        "verdict": analysis.get("verdict"),
                        "conviction": analysis.get("conviction"),
                        "reasons": fail_reasons,
                    })
                    logger.info(f"  {ticker} did not pass threshold — skipping persist")
                    await asyncio.sleep(ANALYSIS_DELAY_SECONDS)
                    continue

                stats["threshold_passed"] += 1
                stats["passed_tickers"].append(ticker)

                # Persist
                if not dry_run:
                    logger.info("=" * 60)
                    logger.info(f"BRAIN PIPELINE — Step 4: Persisting {ticker}")
                    logger.info("=" * 60)
                    await _persist_opportunity(session, candidate, analysis, evidence)
                    await _persist_narrative(session, candidate, analysis, evidence)
                    stats["persisted"] += 1
                else:
                    logger.info(f"  DRY RUN — would persist {ticker}")

            except Exception as e:
                logger.error(f"  Pipeline error for {ticker}: {e}", exc_info=True)
                stats["errors"].append(f"{ticker}: {str(e)}")

            await asyncio.sleep(ANALYSIS_DELAY_SECONDS)

        if not dry_run:
            await session.commit()
            logger.info("DB commit complete")

    # ── Summary ───────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("BRAIN PIPELINE — Summary")
    logger.info("=" * 60)
    logger.info(f"  Candidates scanned: {stats['candidates_scanned']}")
    logger.info(f"  Evidence collected:  {stats['evidence_collected']}")
    logger.info(f"  Analyzed by Claude:  {stats['analyzed']}")
    logger.info(f"  Verified:            {stats['verified']}")
    logger.info(f"  Threshold passed:    {stats['threshold_passed']}")
    logger.info(f"  Persisted to DB:     {stats['persisted']}")
    logger.info(f"  Errors:              {len(stats['errors'])}")
    logger.info(f"  API tokens used:     {stats['total_input_tokens']}in / {stats['total_output_tokens']}out")
    if stats["passed_tickers"]:
        logger.info(f"  Published: {', '.join(stats['passed_tickers'])}")
    if stats["errors"]:
        for err in stats["errors"]:
            logger.error(f"  ERROR: {err}")

    return stats


async def run_brain_single(
    entity_id: str,
    ticker: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Run the Brain pipeline for a single entity (useful for testing).
    Skips the scanner and builds a synthetic candidate.
    """
    from evidence_collector import collect_evidence

    await create_db_and_tables()

    async with AsyncSessionLocal() as session:
        evidence = await collect_evidence(session, entity_id, ticker)
        if not evidence:
            return {"error": f"No evidence found for {entity_id}"}

        candidate = {
            "entity_id": entity_id,
            "ticker": ticker or evidence.get("entity", {}).get("ticker"),
            "company_name": evidence.get("entity", {}).get("name"),
            "reasons": ["manual single-entity run"],
            "priority": 1.0,
            "path_count": 1,
        }

        analysis = await analyze_candidate(candidate, evidence)
        if not analysis:
            return {"error": "Claude analysis failed"}

        analysis.pop("_usage", None)
        analysis = verify_analysis(analysis, evidence)
        passes, reasons = passes_threshold(analysis, evidence)

        result = {
            "candidate": candidate,
            "analysis": analysis,
            "threshold_passed": passes,
            "threshold_reasons": reasons,
        }

        if passes and not dry_run:
            await _persist_opportunity(session, candidate, analysis, evidence)
            await _persist_narrative(session, candidate, analysis, evidence)
            await session.commit()
            result["persisted"] = True

        return result


# ── CLI entry point ──────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the Alpha0 Brain")
    parser.add_argument("--max", type=int, default=None, help="Max candidates to analyze")
    parser.add_argument("--dry-run", action="store_true", help="Analyze but don't persist")
    parser.add_argument("--entity", type=str, default=None, help="Single entity_id to analyze")
    parser.add_argument("--ticker", type=str, default=None, help="Ticker (with --entity)")
    args = parser.parse_args()

    if args.entity:
        result = asyncio.run(run_brain_single(args.entity, args.ticker, args.dry_run))
    else:
        result = asyncio.run(run_brain(max_candidates=args.max, dry_run=args.dry_run))

    import json
    print(json.dumps(result, indent=2, default=str))
