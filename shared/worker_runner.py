"""
Worker runner helper — Sprint 6.5

Uniform integration of structured logging + RunTracker for all ingestion workers.

Usage in a worker's `__main__` block:

    if __name__ == "__main__":
        from shared.worker_runner import run_once_with_tracking, run_once_with_tracking_sync
        mode = os.environ.get("RUN_MODE", "loop")
        if mode == "once":
            # async worker:
            run_once_with_tracking("ingest-trials", run_trial_ingestion)
            # sync worker:
            # run_once_with_tracking_sync("ingest-patents", run_weekly_ingest)
        else:
            asyncio.run(run_loop())

The helper:
  1. Calls `setup_logging(service_name)` from `shared.logging` (JSON in prod, dev formatter otherwise).
  2. Creates a `RunTracker(service_name)`.
  3. Runs the work fn; pipes its return value into the tracker if it returned counts.
  4. Calls `tracker.finish()` which writes both `ingestion_runs` (audit) and `data_freshness`
     (Sprint 6.4 hook) — so every worker run shows up in both.

Work-fn return shape (optional):
    {"records_processed": int, "records_skipped": int, "errors": int, "metadata": dict}
If the fn returns None or a non-dict, RunTracker tallies stay at 0 / success.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable


def _apply_return(tracker, result: Any) -> None:
    if not isinstance(result, dict):
        return
    if "records_processed" in result:
        tracker.run.records_processed = int(result["records_processed"])
    if "records_skipped" in result:
        tracker.run.records_skipped = int(result["records_skipped"])
    if "errors" in result:
        tracker.run.errors = int(result["errors"])
    if "metadata" in result and isinstance(result["metadata"], dict):
        tracker.run.run_metadata = result["metadata"]


async def run_once_with_tracking(
    service_name: str,
    work_fn: Callable[[], Awaitable[Any]],
) -> Any:
    """Run an async one-shot worker function with structured logs + tracking."""
    # Set up structured logging (no-op if already configured upstream)
    try:
        from shared.logging import setup_logging
        setup_logging(service_name)
    except Exception:
        # Fall back to basicConfig if shared.logging isn't importable in this env
        logging.basicConfig(level=logging.INFO)
    log = logging.getLogger(service_name)

    from shared.clients.run_tracker import RunTracker
    tracker = RunTracker(service_name)
    tracker.start()
    try:
        result = await work_fn()
        _apply_return(tracker, result)
        await tracker.finish()
        return result
    except Exception as e:
        log.exception(f"[{service_name}] run failed: {e}")
        tracker.record_error(str(e))
        await tracker.finish()
        raise


def run_once_with_tracking_sync(
    service_name: str,
    work_fn: Callable[[], Any],
) -> Any:
    """Run a sync one-shot worker function with structured logs + tracking."""
    try:
        from shared.logging import setup_logging
        setup_logging(service_name)
    except Exception:
        logging.basicConfig(level=logging.INFO)
    log = logging.getLogger(service_name)

    from shared.clients.run_tracker import RunTracker
    tracker = RunTracker(service_name)
    tracker.start()
    try:
        result = work_fn()
        _apply_return(tracker, result)
        # RunTracker.finish is async; the freshness upsert it triggers also is.
        asyncio.run(tracker.finish())
        return result
    except Exception as e:
        log.exception(f"[{service_name}] run failed: {e}")
        tracker.record_error(str(e))
        asyncio.run(tracker.finish())
        raise
