from fastapi import APIRouter


router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    """Railway health check endpoint."""
    return {
        "status": "ok",
        "service": "alpha0engine-api",
        "version": "0.1.0",
    }
