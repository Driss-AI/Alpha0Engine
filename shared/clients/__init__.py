"""
Shared clients package.

Postgres is the universal dependency (every service uses it) so it's imported
eagerly. Redis (`redis`) and R2 (`boto3`) are NOT universal — importing them at
package load forced every Postgres-only service to install those deps or crash
with ModuleNotFoundError on startup (this bit ingest-news + brain on `redis`, and
would have bitten ingest-fda/capex/alert-engine on `boto3`).

So redis_client + r2 names are exposed LAZILY via PEP 562 module __getattr__:
they're only imported the first time the name is actually accessed
(`from shared.clients import get_redis`). Importing a sibling submodule directly
(`from shared.clients.postgres import ...`) no longer drags in redis/boto3.
"""
from .postgres import create_db_and_tables, get_session

# name -> (submodule, attribute). Imported on first access, not at package load.
_LAZY: dict[str, tuple[str, str]] = {
    "get_redis": (".redis_client", "get_redis"),
    "publish_signal": (".redis_client", "publish_signal"),
    "cache_set": (".redis_client", "cache_set"),
    "cache_get": (".redis_client", "cache_get"),
    "r2_upload": (".r2", "upload"),
    "r2_download": (".r2", "download"),
    "r2_key": (".r2", "r2_key"),
}


def __getattr__(name: str):  # PEP 562
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    module = importlib.import_module(target[0], __name__)
    return getattr(module, target[1])


def __dir__() -> list[str]:
    return sorted([*globals().keys(), *_LAZY.keys()])


__all__ = [
    "get_session", "create_db_and_tables",
    "get_redis", "publish_signal", "cache_set", "cache_get",
    "r2_upload", "r2_download", "r2_key",
]
