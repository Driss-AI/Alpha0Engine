"""
Entity Resolver — Redis stream consumer + daily batch re-resolution.
Resolution order: CIK > domain > github_org > fuzzy name > create new
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import json, logging, asyncio, schedule, time
from dotenv import load_dotenv
from resolver import EntityResolver

load_dotenv()
logging.basicConfig(level=os.environ.get("LOG_LEVEL","INFO"), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("entity-resolver")


async def consume_stream():
    from shared.clients.redis_client import get_redis, STREAMS
    redis = await get_redis()
    stream_key = STREAMS["raw_signals"]
    group = "entity-resolver"
    try:
        await redis.xgroup_create(stream_key, group, id="0", mkstream=True)
        log.info(f"Consumer group '{group}' created")
    except Exception:
        pass
    resolver = EntityResolver()
    log.info("Stream consumer ready...")
    while True:
        try:
            messages = await redis.xreadgroup(groupname=group, consumername="resolver-1",
                streams={stream_key: ">"}, count=50, block=5000)
            if not messages: continue
            for _stream, entries in messages:
                for entry_id, fields in entries:
                    try:
                        payload = json.loads(fields.get("payload","{}"))
                        await resolver.resolve_and_update(payload)
                        await redis.xack(stream_key, group, entry_id)
                    except Exception as e:
                        log.error(f"Resolve error {entry_id}: {e}")
        except Exception as e:
            log.error(f"Stream error: {e}")
            await asyncio.sleep(5)


async def run_daily_batch():
    from shared.clients.postgres import AsyncSessionLocal
    from shared.schemas.signals import Signal
    from sqlmodel import select
    log.info("Daily batch re-resolution starting...")
    resolver = EntityResolver()
    async with AsyncSessionLocal() as session:
        result = await session.exec(select(Signal).where(Signal.entity_id == "UNRESOLVED").limit(1000))
        unresolved = result.all()
    log.info(f"Unresolved signals: {len(unresolved)}")
    for signal in unresolved:
        try:
            await resolver.resolve_and_update(signal.raw_data)
        except Exception as e:
            log.error(f"Batch error {signal.id}: {e}")
    log.info("Batch complete.")


def main():
    log.info("Entity resolver starting...")
    schedule.every().day.at("08:00").do(lambda: asyncio.get_event_loop().run_until_complete(run_daily_batch()))
    asyncio.get_event_loop().run_until_complete(consume_stream())


if __name__ == "__main__":
    main()
