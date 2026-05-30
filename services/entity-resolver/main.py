"""
Entity Resolver — Redis stream consumer + daily batch re-resolution.
Resolution order: CIK > domain > github_org > fuzzy name > create new
Features: retry counter (max 3), dead-letter queue for poison messages.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import json
import logging
import asyncio
from dotenv import load_dotenv
from resolver import EntityResolver

load_dotenv()
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("entity-resolver")

MAX_RETRIES = 3


async def _process_entry(resolver, redis, stream_key, group, entry_id, fields):
    """Process a single stream entry with retry tracking."""
    payload = json.loads(fields.get("payload", "{}"))
    retry_count = int(fields.get("retry_count", "0"))

    try:
        await resolver.resolve_and_update(payload)
        await redis.xack(stream_key, group, entry_id)
    except Exception as e:
        retry_count += 1
        log.error(f"Resolve error {entry_id} (attempt {retry_count}/{MAX_RETRIES}): {e}")

        if retry_count >= MAX_RETRIES:
            # Send to dead-letter queue
            from shared.clients.redis_client import publish_to_dlq
            await publish_to_dlq(
                original_payload=payload,
                error=str(e),
                source_stream="raw_signals",
                retry_count=retry_count,
            )
            await redis.xack(stream_key, group, entry_id)
            log.warning(f"Message {entry_id} sent to DLQ after {MAX_RETRIES} retries")
        else:
            # Re-add to stream with incremented retry count for later processing
            await redis.xadd(
                stream_key,
                {"payload": json.dumps(payload, default=str), "retry_count": str(retry_count)},
                maxlen=100_000,
                approximate=True,
            )
            await redis.xack(stream_key, group, entry_id)


async def consume_stream():
    from shared.clients.redis_client import get_redis, STREAMS
    redis = await get_redis()
    stream_key = STREAMS["raw_signals"]
    group = "entity-resolver"
    try:
        await redis.xgroup_create(stream_key, group, id="0", mkstream=True)
        log.info(f"Consumer group '{group}' created")
    except Exception:
        pass  # Group already exists — expected
    resolver = EntityResolver()
    log.info("Stream consumer ready...")
    while True:
        try:
            messages = await redis.xreadgroup(groupname=group, consumername="resolver-1",
                streams={stream_key: ">"}, count=50, block=5000)
            if not messages:
                continue
            for _stream, entries in messages:
                for entry_id, fields in entries:
                    await _process_entry(resolver, redis, stream_key, group, entry_id, fields)
        except Exception as e:
            log.error(f"Stream consumer error: {e}")
            await asyncio.sleep(5)


async def run_daily_batch():
    from shared.clients.postgres import AsyncSessionLocal
    from shared.schemas.signals import Signal
    from sqlmodel import select, update
    log.info("Daily batch re-resolution starting...")
    resolver = EntityResolver()
    resolved_count = 0
    failed_count = 0

    async with AsyncSessionLocal() as session:
        result = await session.exec(
            select(Signal).where(Signal.resolution_status == "pending").limit(1000)
        )
        unresolved = result.all()
    log.info(f"Pending resolution signals: {len(unresolved)}")

    for signal in unresolved:
        try:
            entity_id = await resolver.resolve_and_update(signal.raw_data)
            if entity_id:
                async with AsyncSessionLocal() as session:
                    await session.exec(
                        update(Signal)
                        .where(Signal.id == signal.id)
                        .values(entity_id=entity_id, resolution_status="resolved")
                    )
                    await session.commit()
                resolved_count += 1
            else:
                failed_count += 1
        except Exception as e:
            log.error(f"Batch resolve error {signal.id}: {e}")
            failed_count += 1

    # Mark signals that have failed too many batch attempts
    log.info(f"Batch complete. Resolved: {resolved_count}, Failed: {failed_count}")


async def drain_and_resolve():
    """Drain pending Redis stream messages, then run batch re-resolution."""
    from shared.clients.redis_client import get_redis, STREAMS
    redis = await get_redis()
    stream_key = STREAMS["raw_signals"]
    group = "entity-resolver"
    try:
        await redis.xgroup_create(stream_key, group, id="0", mkstream=True)
    except Exception:
        pass

    resolver = EntityResolver()
    drained = 0

    while True:
        messages = await redis.xreadgroup(
            groupname=group, consumername="resolver-1",
            streams={stream_key: ">"}, count=100, block=1000,
        )
        if not messages:
            break
        for _stream, entries in messages:
            for entry_id, fields in entries:
                await _process_entry(resolver, redis, stream_key, group, entry_id, fields)
                drained += 1

    log.info(f"Drained {drained} pending stream messages")
    await run_daily_batch()


def main():
    log.info("Entity resolver starting...")

    mode = os.environ.get("RUN_MODE", "loop")
    if mode == "once":
        log.info("RUN_MODE=once — draining stream + batch resolve then exiting")
        from shared.worker_runner import run_once_with_tracking
        asyncio.get_event_loop().run_until_complete(run_once_with_tracking("entity-resolver", drain_and_resolve))
        log.info("Entity resolver complete. Exiting.")
        return

    import schedule
    schedule.every().day.at("08:00").do(lambda: asyncio.get_event_loop().run_until_complete(run_daily_batch()))
    asyncio.get_event_loop().run_until_complete(consume_stream())


if __name__ == "__main__":
    main()
