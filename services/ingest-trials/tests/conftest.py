import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")

_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REPO_ROOT = os.path.abspath(os.path.join(_SERVICE_DIR, "..", ".."))
for p in (_SERVICE_DIR, _REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
