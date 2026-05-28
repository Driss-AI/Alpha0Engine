import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport

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
