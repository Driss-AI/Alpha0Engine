"""
API Key authentication middleware.

Two access levels:
- viewer: read-only (GET requests)
- admin: full access (GET + POST/PATCH/PUT/DELETE)

Key is passed via X-API-Key header or api_key query param.
In dev mode with no API_SECRET_KEY set, auth is bypassed.
"""
from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader, APIKeyQuery

from shared.config import API_SECRET_KEY, IS_DEV

_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)
_query_scheme = APIKeyQuery(name="api_key", auto_error=False)


def _extract_key(
    header_key: str | None = Security(_header_scheme),
    query_key: str | None = Security(_query_scheme),
) -> str | None:
    return header_key or query_key


def require_api_key(
    request: Request,
    key: str | None = Depends(_extract_key),
) -> str:
    if IS_DEV and not API_SECRET_KEY:
        return "dev-bypass"

    if not key:
        raise HTTPException(status_code=401, detail="Missing API key")
    if key != API_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return key


def require_admin_key(
    request: Request,
    key: str = Depends(require_api_key),
) -> str:
    if key == "dev-bypass":
        return key

    if not key or key != API_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Admin access required")
    return key
