#!/usr/bin/env python3
"""
Backup Verification
===================
Proves a Postgres backup is actually restorable — a backup you have never
restored is not a backup. This script:

  1. Dumps the source database with pg_dump.
  2. Creates a throwaway temp database on the same server.
  3. Restores the dump into the temp database.
  4. Runs health checks: alembic version == expected head, all expected
     tables present, and core tables are queryable.
  5. Drops the temp database (always, even on failure).

Exit code 0 = backup verified restorable, 1 = verification failed.

Usage:
    python scripts/verify_backup.py
    python scripts/verify_backup.py --expected-head d4e5f6a7b8c9
    SOURCE_DATABASE_URL=postgresql://... python scripts/verify_backup.py

Requires `pg_dump` and `psql` on PATH (the standard Postgres client tools).
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse, urlunparse

# Tables that must exist in a healthy restore. Core subset — not exhaustive.
EXPECTED_TABLES = [
    "entities",
    "signals",
    "equity_screens",
    "score_snapshots",
    "user_watchlist",
    "alembic_version",
]

DEFAULT_EXPECTED_HEAD = "d4e5f6a7b8c9"


def _normalize(url: str) -> str:
    # pg client tools speak postgresql://, not the asyncpg/SQLAlchemy variants.
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgres://", "postgresql://"
    )


def _admin_url(url: str) -> str:
    """Same server/credentials, but pointed at the default `postgres` db so we
    can CREATE/DROP the temp database."""
    parts = urlparse(url)
    return urlunparse(parts._replace(path="/postgres"))


def _swap_db(url: str, db_name: str) -> str:
    parts = urlparse(url)
    return urlunparse(parts._replace(path=f"/{db_name}"))


def _run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _psql_scalar(url: str, sql: str) -> str:
    res = _run(["psql", url, "-tAc", sql])
    if res.returncode != 0:
        raise RuntimeError(f"psql failed: {res.stderr.strip()}")
    return res.stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify a Postgres backup is restorable.")
    ap.add_argument(
        "--expected-head",
        default=os.environ.get("EXPECTED_ALEMBIC_HEAD", DEFAULT_EXPECTED_HEAD),
        help="Alembic revision the restored DB must be stamped at.",
    )
    ap.add_argument("--keep-temp", action="store_true", help="Do not drop the temp DB (debug).")
    args = ap.parse_args()

    source = _normalize(
        os.environ.get("SOURCE_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    )
    if not source:
        print("ERROR: set SOURCE_DATABASE_URL or DATABASE_URL", file=sys.stderr)
        return 1

    admin = _admin_url(source)
    temp_db = f"alpha0_verify_{int(time.time())}"
    temp_url = _swap_db(source, temp_db)
    dump_path = os.path.join(tempfile.gettempdir(), f"{temp_db}.sql")

    print(f"→ Source:  {urlparse(source).path.lstrip('/')}")
    print(f"→ Temp DB: {temp_db}")

    ok = True
    try:
        # 1. Dump
        print("→ Dumping source database...")
        dump = _run(["pg_dump", "--no-owner", "--no-privileges", "-f", dump_path, source])
        if dump.returncode != 0:
            print(f"FAIL: pg_dump failed: {dump.stderr.strip()}", file=sys.stderr)
            return 1
        size_mb = os.path.getsize(dump_path) / 1_048_576
        print(f"  dump OK ({size_mb:.1f} MB)")

        # 2. Create temp DB
        print("→ Creating temp database...")
        create = _run(["psql", admin, "-c", f'CREATE DATABASE "{temp_db}"'])
        if create.returncode != 0:
            print(f"FAIL: could not create temp DB: {create.stderr.strip()}", file=sys.stderr)
            return 1

        # 3. Restore
        print("→ Restoring into temp database...")
        restore = _run(["psql", temp_url, "-v", "ON_ERROR_STOP=1", "-f", dump_path])
        if restore.returncode != 0:
            print(f"FAIL: restore failed: {restore.stderr.strip()}", file=sys.stderr)
            ok = False
        else:
            print("  restore OK")

        # 4. Health checks
        if ok:
            print("→ Validating restored schema...")
            head = _psql_scalar(temp_url, "SELECT version_num FROM alembic_version")
            if head == args.expected_head:
                print(f"  alembic head OK ({head})")
            else:
                print(f"FAIL: alembic head {head!r} != expected {args.expected_head!r}", file=sys.stderr)
                ok = False

            present = set(
                _psql_scalar(
                    temp_url,
                    "SELECT string_agg(tablename, ',') FROM pg_tables WHERE schemaname='public'",
                ).split(",")
            )
            missing = [t for t in EXPECTED_TABLES if t not in present]
            if missing:
                print(f"FAIL: missing tables after restore: {missing}", file=sys.stderr)
                ok = False
            else:
                print(f"  all {len(EXPECTED_TABLES)} expected tables present")

            # Core tables must be queryable (catches corrupt restores).
            for tbl in ("entities", "signals"):
                count = _psql_scalar(temp_url, f"SELECT count(*) FROM {tbl}")
                print(f"  {tbl}: {count} rows")

    finally:
        # 5. Always drop the temp DB
        if not args.keep_temp:
            print("→ Dropping temp database...")
            _run(["psql", admin, "-c", f'DROP DATABASE IF EXISTS "{temp_db}"'])
        try:
            os.remove(dump_path)
        except OSError:
            pass

    print("\n" + ("✓ BACKUP VERIFIED — restore succeeded" if ok else "✗ BACKUP VERIFICATION FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
