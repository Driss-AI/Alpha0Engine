import pytest
from unittest.mock import patch
from httpx import AsyncClient

# The conftest stubs shared.clients.postgres and sets up the test DB.
# For auth tests we need to control the API_SECRET_KEY and IS_DEV flags.


API_KEY = "test-secret-key-12345"

VIEWER_ENDPOINTS = [
    ("GET", "/api/v1/entities"),
    ("GET", "/api/v1/signals"),
    ("GET", "/api/v1/watchlist"),
    ("GET", "/api/v1/catalysts"),
    ("GET", "/api/v1/1000x/deltas"),
    ("GET", "/api/v1/1000x/movers"),
    ("GET", "/api/v1/brain/picks"),
    ("GET", "/api/v1/brain/stats"),
]

ADMIN_ENDPOINTS = [
    ("POST", "/api/v1/watchlist", {"ticker": "AAPL", "priority": "high"}),
    ("POST", "/api/v1/catalysts/pin", {
        "ticker": "MRNA", "catalyst_type": "fda", "title": "test", "status": "upcoming",
    }),
    ("POST", "/api/v1/entities", {"name": "Test Corp"}),
    ("POST", "/api/v1/signals", {
        "entity_id": "ent-1", "signal_type": "news_mention",
        "signal_date": "2026-01-01T00:00:00", "source": "manual",
    }),
]


@pytest.fixture
def auth_patches():
    """Patch auth module to enforce key validation (not dev-bypass)."""
    with (
        patch("middleware.auth.IS_DEV", False),
        patch("middleware.auth.API_SECRET_KEY", API_KEY),
    ):
        yield


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", VIEWER_ENDPOINTS)
async def test_viewer_endpoint_rejects_no_key(client: AsyncClient, auth_patches, method, path):
    resp = await client.request(method, path)
    assert resp.status_code == 401, f"{method} {path} should return 401 without key"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", VIEWER_ENDPOINTS)
async def test_viewer_endpoint_rejects_bad_key(client: AsyncClient, auth_patches, method, path):
    resp = await client.request(method, path, headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 403, f"{method} {path} should return 403 with bad key"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", VIEWER_ENDPOINTS)
async def test_viewer_endpoint_accepts_valid_key(client: AsyncClient, auth_patches, method, path):
    resp = await client.request(method, path, headers={"X-API-Key": API_KEY})
    assert resp.status_code in (200, 422), f"{method} {path} should succeed with valid key"


@pytest.mark.asyncio
async def test_key_via_query_param(client: AsyncClient, auth_patches):
    resp = await client.get("/api/v1/entities", params={"api_key": API_KEY})
    assert resp.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", ADMIN_ENDPOINTS)
async def test_admin_endpoint_rejects_no_key(client: AsyncClient, auth_patches, method, path, body):
    resp = await client.request(method, path, json=body)
    assert resp.status_code == 401, f"{method} {path} should return 401 without key"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", ADMIN_ENDPOINTS)
async def test_admin_endpoint_accepts_admin_key(client: AsyncClient, auth_patches, method, path, body):
    resp = await client.request(method, path, json=body, headers={"X-API-Key": API_KEY})
    assert resp.status_code in (200, 201), f"{method} {path} should succeed with admin key"


@pytest.mark.asyncio
async def test_health_no_auth_required(client: AsyncClient, auth_patches):
    resp = await client.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_dev_mode_bypasses_auth(client: AsyncClient):
    """In dev mode with no API_SECRET_KEY, auth is bypassed."""
    with (
        patch("middleware.auth.IS_DEV", True),
        patch("middleware.auth.API_SECRET_KEY", ""),
    ):
        resp = await client.get("/api/v1/entities")
        assert resp.status_code == 200


# ── Sprint 6.2: viewer key separation ──────────────────────────────────────
# Two distinct keys: admin (writes) and viewer (read-only, safe to embed in HTML).

VIEWER_KEY = "test-viewer-key-67890"


@pytest.fixture
def auth_patches_with_viewer():
    """Enforce key validation with BOTH admin and viewer keys configured."""
    with (
        patch("middleware.auth.IS_DEV", False),
        patch("middleware.auth.API_SECRET_KEY", API_KEY),
        patch("middleware.auth.VIEWER_API_KEY", VIEWER_KEY),
    ):
        yield


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", VIEWER_ENDPOINTS)
async def test_viewer_key_accepted_on_reads(
    client: AsyncClient, auth_patches_with_viewer, method, path
):
    """Viewer key grants read access (200, or 422 on missing-param edge cases)."""
    resp = await client.request(method, path, headers={"X-API-Key": VIEWER_KEY})
    assert resp.status_code in (200, 422), (
        f"{method} {path} should accept viewer key, got {resp.status_code}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", ADMIN_ENDPOINTS)
async def test_viewer_key_blocked_on_writes(
    client: AsyncClient, auth_patches_with_viewer, method, path, body
):
    """Viewer key MUST NOT be able to write — admin key required."""
    resp = await client.request(method, path, json=body, headers={"X-API-Key": VIEWER_KEY})
    assert resp.status_code == 403, (
        f"{method} {path} accepted viewer key for write — admin scope leak. "
        f"Got {resp.status_code}"
    )


@pytest.mark.asyncio
async def test_admin_key_still_grants_reads(client: AsyncClient, auth_patches_with_viewer):
    """Admin key implies viewer scope (back-compat)."""
    resp = await client.get("/api/v1/entities", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_unknown_key_rejected_even_with_viewer_configured(
    client: AsyncClient, auth_patches_with_viewer
):
    resp = await client.get("/api/v1/entities", headers={"X-API-Key": "neither-admin-nor-viewer"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_empty_viewer_key_does_not_authorize_empty_header(
    client: AsyncClient,
):
    """If VIEWER_API_KEY is unset (""), an empty X-API-Key header must not pass."""
    with (
        patch("middleware.auth.IS_DEV", False),
        patch("middleware.auth.API_SECRET_KEY", API_KEY),
        patch("middleware.auth.VIEWER_API_KEY", ""),
    ):
        # No header → 401
        resp = await client.get("/api/v1/entities")
        assert resp.status_code == 401
        # Empty header → 401 (not 403, because no key is "missing" not "invalid")
        resp = await client.get("/api/v1/entities", headers={"X-API-Key": ""})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_html_does_not_leak_admin_key(client: AsyncClient):
    """Dashboard HTML at / must inject the viewer key, never the admin key."""
    with (
        patch("services.api.main.API_SECRET_KEY", API_KEY),
        patch("services.api.main.VIEWER_API_KEY", VIEWER_KEY),
        patch("services.api.main.IS_DEV", False),
    ):
        resp = await client.get("/")
        # Even if the static file doesn't exist in tests, the placeholder fallback shouldn't leak.
        assert API_KEY not in resp.text, "Admin API_SECRET_KEY leaked into dashboard HTML"
