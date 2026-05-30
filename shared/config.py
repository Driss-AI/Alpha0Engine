"""
Environment-aware configuration for Alpha0Engine.
"""
import os

ENV = os.environ.get("ENVIRONMENT", "development")

IS_DEV = ENV == "development"
IS_STAGING = ENV == "staging"
IS_PROD = ENV == "production"

LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG" if IS_DEV else "INFO")

API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "")  # admin / write key
VIEWER_API_KEY = os.environ.get("VIEWER_API_KEY", "")  # read-only key (safe to embed in public HTML)

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]
if IS_DEV and not ALLOWED_ORIGINS:
    ALLOWED_ORIGINS = ["*"]

RATE_LIMIT = os.environ.get("RATE_LIMIT", "60/minute")

AUTO_CREATE_TABLES = IS_DEV
