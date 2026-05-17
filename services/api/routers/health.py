from fastapi import APIRouter
from shared.clients.redis_client import ping as redis_ping

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    """Railway health check endpoint."""
    redis_ok = await redis_ping()
    return {
        "status": "ok",
        "service": "alpha0engine-api",
        "version": "0.1.0",
        "redis": "ok" if redis_ok else "degraded",
    }
