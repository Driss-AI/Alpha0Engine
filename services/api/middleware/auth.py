"""
API Key authentication middleware.

Two access levels:
- viewer: read-only (GET) — `VIEWER_API_KEY` or `API_SECRET_KEY`
- admin:  read + write    — `API_SECRET_KEY` only

The viewer key is safe to embed in public dashboard HTML; the admin key MUST NOT be.
If `VIEWER_API_KEY` is unset, viewer-scope endpoints accept only the admin key (and the
dashboard's read calls will fail until the env var is set — by design, to surface the
misconfiguration rather than silently leak the admin key again).

Key is passed via X-API-Key header or api_key query param.
In dev mode with no API_SECRET_KEY set, auth is bypassed.
"""
from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader, APIKeyQuery

from shared.config import API_SECRET_KEY, IS_DEV, VIEWER_API_KEY

_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)
_query_scheme = APIKeyQuery(name="api_key", auto_error=False)


def _extract_key(
    header_key: str | None = Security(_header_scheme),
    query_key: str | None = Security(_query_scheme),
) -> str | None:
    return header_key or query_key


def _valid_viewer_keys() -> set[str]:
    """Keys that grant viewer (read-only) scope. Admin key always implies viewer."""
    keys = {API_SECRET_KEY}
    if VIEWER_API_KEY:
        keys.add(VIEWER_API_KEY)
    # Filter out empty string — never accept ""
    return {k for k in keys if k}


def require_api_key(
    request: Request,
    key: str | None = Depends(_extract_key),
) -> str:
    if IS_DEV and not API_SECRET_KEY:
        return "dev-bypass"

    if not key:
        raise HTTPException(status_code=401, detail="Missing API key")
    if key not in _valid_viewer_keys():
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
