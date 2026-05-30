#!/usr/bin/env python3
"""
Daily pipeline orchestrator — Sprint 6.3.

Runs the full Alpha0Engine ingestion → resolution → screening → brain pipeline
in sequence. Each worker is invoked as a subprocess with RUN_MODE=once so it
exits when its one-shot job is done (matching Railway cron behavior).

Each worker writes its own `ingestion_runs` row via `shared.clients.run_tracker`.
This orchestrator writes a single summary `ingestion_runs` row of its own at the
end (`service_name='pipeline-orchestrator'`).

Usage:
    python scripts/run_daily_pipeline.py
    python scripts/run_daily_pipeline.py --only ingest-edgar,entity-resolver
    python scripts/run_daily_pipeline.py --skip brain,nlp-engine
    python scripts/run_daily_pipeline.py --dry-run    # show what would run

Exit codes:
    0  all critical steps succeeded (soft-fail steps may have failed)
    1  at least one critical step failed
    2  user/env error (bad --only spec, etc.)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@dataclass
class Step:
    name: str                          # unique step id (also worker dir)
    script: str                        # path relative to repo root
    critical: bool = False             # if True, failure aborts the pipeline
    extra_env: dict[str, str] = field(default_factory=dict)
    description: str = ""

    def cmd(self) -> list[str]:
        return [sys.executable, str(REPO_ROOT / self.script)]


# Pipeline order (matches the spec from SPRINT_PLAN.md S6.3):
#   universe discovery → prices → SEC/EDGAR → 8-K → patents → trials → news
#   → Form 4 → 13F → entity resolution → fundamental screener → risk filter
#   → screener-1000x → brain → alerts (alerts deferred until S9 alert-engine ships)
PIPELINE: list[Step] = [
    Step("universe-discovery",   "services/ingest-prices/main.py",        critical=True,
         extra_env={"RUN_MODE": "discover"},
         description="Discover US public-equity universe from SEC ticker list"),
    Step("ingest-prices",        "services/ingest-prices/main.py",        critical=True,
         description="OHLCV + market cap for the active universe"),
    Step("ingest-edgar",         "services/ingest-edgar/main.py",         critical=True,
         description="SEC EDGAR Form D + filings (primary catalyst source)"),
    Step("ingest-8k",            "services/ingest-8k/main.py",            critical=False,
         description="8-K material events"),
    Step("ingest-patents",       "services/ingest-patents/main.py",       critical=False,
         description="USPTO patent grants"),
    Step("ingest-trials",        "services/ingest-trials/main.py",        critical=False,
         description="ClinicalTrials.gov (biotech lane)"),
    Step("ingest-news",          "services/ingest-news/main.py",          critical=False,
         description="Finnhub news (soft-fails without FINNHUB_API_KEY)"),
    Step("ingest-form4",         "services/ingest-form4/main.py",         critical=False,
         description="Insider Form 4 transactions"),
    Step("ingest-13f",           "services/ingest-13f/main.py",           critical=False,
         description="13F institutional positions"),
    Step("ingest-github",        "services/ingest-github/main.py",        critical=False,
         description="GitHub Archive technical signals"),
    Step("entity-resolver",      "services/entity-resolver/main.py",      critical=True,
         description="Resolve pending signals to entities"),
    Step("nlp-engine",           "services/nlp-engine/main.py",           critical=False,
         description="Theme detection + embeddings"),
    Step("fundamental-screener", "services/fundamental-screener/main.py", critical=False,
         description="Fundamental scoring layer"),
    Step("risk-filter",          "services/risk-filter/main.py",          critical=False,
         description="Risk flags + hype detection"),
    Step("screener-1000x",       "services/screener-1000x/main.py",       critical=True,
         description="5-lens asymmetric composite (terminal scoring step)"),
    Step("brain",                "services/brain/main.py",                critical=False,
         description="Brain candidate scan + narratives"),
    Step("alert-engine",         "services/alert-engine/main.py",         critical=False,
         description="Dispatch DEEP_DIVE/SETUP_READY alerts to Telegram (S9)"),
]


# ── execution ─────────────────────────────────────────────────────────────

@dataclass
class StepResult:
    step: Step
    started_at: datetime
    duration_s: float
    exit_code: int
    skipped: bool = False

    @property
    def status(self) -> str:
        if self.skipped:
            return "SKIP"
        if self.exit_code == 0:
            return "OK"
        return "CRITICAL-FAIL" if self.step.critical else "SOFT-FAIL"


def run_step(step: Step, *, dry_run: bool) -> StepResult:
    started = datetime.now(timezone.utc)
    if dry_run:
        return StepResult(step, started, 0.0, 0, skipped=False)

    env = os.environ.copy()
    env.setdefault("RUN_MODE", "once")
    env.update(step.extra_env)
    env.setdefault("PYTHONPATH", str(REPO_ROOT))

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            step.cmd(),
            cwd=REPO_ROOT,
            env=env,
            timeout=60 * 30,  # 30 min per step
            check=False,
        )
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        exit_code = 124
    except FileNotFoundError:
        exit_code = 127
    duration = time.monotonic() - t0
    return StepResult(step, started, duration, exit_code)


async def _record_summary(results: list[StepResult]) -> None:
    """Write one ingestion_runs row summarizing the orchestrator's run."""
    try:
        from shared.clients.run_tracker import RunTracker
    except Exception as e:
        print(f"  (could not import RunTracker, skipping summary row: {e})")
        return

    tracker = RunTracker("pipeline-orchestrator")
    tracker.start()
    for r in results:
        if r.skipped:
            tracker.record_skip()
        elif r.exit_code == 0:
            tracker.record_success()
        else:
            tracker.record_error(f"{r.step.name} exit={r.exit_code} duration={r.duration_s:.1f}s")
    tracker.run.run_metadata = {
        "steps": [
            {
                "name": r.step.name,
                "status": r.status,
                "exit_code": r.exit_code,
                "duration_s": round(r.duration_s, 1),
                "critical": r.step.critical,
            }
            for r in results
        ]
    }
    await tracker.finish()


# ── cli ───────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", help="Comma-separated step names to include (others skipped)")
    p.add_argument("--skip", help="Comma-separated step names to skip")
    p.add_argument("--dry-run", action="store_true", help="Print what would run, don't execute")
    p.add_argument("--continue-on-critical", action="store_true",
                   help="Don't abort the pipeline when a critical step fails")
    return p.parse_args(argv)


def _filter_steps(args: argparse.Namespace) -> list[tuple[Step, bool]]:
    """Return [(step, should_skip), ...]."""
    only = set(s.strip() for s in args.only.split(",")) if args.only else None
    skip = set(s.strip() for s in args.skip.split(",")) if args.skip else set()
    valid_names = {s.name for s in PIPELINE}
    bad = ((only or set()) | skip) - valid_names
    if bad:
        print(f"unknown step(s): {sorted(bad)}", file=sys.stderr)
        print(f"valid: {sorted(valid_names)}", file=sys.stderr)
        sys.exit(2)
    return [
        (step, (only is not None and step.name not in only) or step.name in skip)
        for step in PIPELINE
    ]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    plan = _filter_steps(args)

    print(f"\n{'─' * 78}")
    print(f"Alpha0Engine daily pipeline   ({datetime.now(timezone.utc).isoformat(timespec='seconds')})")
    if args.dry_run:
        print("DRY RUN — no subprocesses will execute")
    print(f"{'─' * 78}")
    for step, skipped in plan:
        marker = "skip" if skipped else ("crit" if step.critical else "soft")
        print(f"  [{marker}] {step.name:24s} — {step.description}")
    print(f"{'─' * 78}\n")

    results: list[StepResult] = []
    aborted_after: str | None = None
    for step, should_skip in plan:
        if should_skip:
            results.append(StepResult(step, datetime.now(timezone.utc), 0.0, 0, skipped=True))
            print(f"  · SKIP  {step.name}")
            continue
        if aborted_after:
            results.append(StepResult(step, datetime.now(timezone.utc), 0.0, 0, skipped=True))
            print(f"  · SKIP  {step.name}  (aborted after {aborted_after})")
            continue

        print(f"  → {step.name} …", flush=True)
        r = run_step(step, dry_run=args.dry_run)
        results.append(r)
        sym = "✓" if r.exit_code == 0 else ("✗ CRIT" if step.critical else "✗ soft")
        print(f"    {sym}  exit={r.exit_code}  {r.duration_s:.1f}s")

        if r.exit_code != 0 and step.critical and not args.continue_on_critical:
            aborted_after = step.name

    # ── summary ──
    print(f"\n{'─' * 78}")
    print(f"{'STEP':<26}{'STATUS':<16}{'EXIT':<6}{'TIME':<8}")
    print(f"{'─' * 78}")
    for r in results:
        print(f"{r.step.name:<26}{r.status:<16}{r.exit_code:<6}{r.duration_s:6.1f}s")
    print(f"{'─' * 78}")

    critical_failures = [r for r in results if not r.skipped and r.exit_code != 0 and r.step.critical]
    soft_failures = [r for r in results if not r.skipped and r.exit_code != 0 and not r.step.critical]
    total_time = sum(r.duration_s for r in results)
    ok_count = sum(1 for r in results if not r.skipped and r.exit_code == 0)

    print(f"Total: {len(results)} steps, {ok_count} ok, "
          f"{len(soft_failures)} soft-fail, {len(critical_failures)} critical-fail "
          f"in {total_time:.1f}s")
    if aborted_after:
        print(f"Pipeline aborted after critical failure in: {aborted_after}")

    if not args.dry_run:
        try:
            asyncio.run(_record_summary(results))
        except Exception as e:
            print(f"  (warning: could not write pipeline_run summary row: {e})")

    return 1 if critical_failures else 0


if __name__ == "__main__":
    sys.exit(main())
