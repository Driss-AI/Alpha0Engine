"""
Alembic migration chain tests.

Test 1 (offline — no DB): Verify the revision chain is consistent.
  Every migration has a valid down_revision, no orphans, single head.

Test 2 (requires Postgres, marked for CI): upgrade/downgrade round-trip.
  Skipped locally if DATABASE_URL points to SQLite.
"""
import os
import sys
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _get_alembic_config() -> Config:
    ini_path = os.path.join(PROJECT_ROOT, "alembic.ini")
    cfg = Config(ini_path)
    cfg.set_main_option("script_location", os.path.join(PROJECT_ROOT, "alembic"))
    return cfg


def test_migration_chain_is_linear():
    """All revisions form a single linear chain with one head."""
    cfg = _get_alembic_config()
    script = ScriptDirectory.from_config(cfg)

    revisions = list(script.walk_revisions())
    assert len(revisions) >= 1, "Expected at least one migration"

    heads = script.get_heads()
    assert len(heads) == 1, f"Expected single head, got {heads}"


def test_no_orphan_revisions():
    """Every revision (except the first) has a valid parent."""
    cfg = _get_alembic_config()
    script = ScriptDirectory.from_config(cfg)

    rev_ids = set()
    for rev in script.walk_revisions():
        rev_ids.add(rev.revision)

    for rev in script.walk_revisions():
        if rev.down_revision is not None:
            if isinstance(rev.down_revision, tuple):
                for dr in rev.down_revision:
                    assert dr in rev_ids, f"Orphan: {rev.revision} references missing {dr}"
            else:
                assert rev.down_revision in rev_ids, (
                    f"Orphan: {rev.revision} references missing {rev.down_revision}"
                )


def test_head_matches_expected():
    """Current head should be the Sprint 4 migration."""
    cfg = _get_alembic_config()
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert "c3d4e5f6a7b8" in heads, f"Expected head c3d4e5f6a7b8, got {heads}"


def test_all_revisions_have_upgrade_and_downgrade():
    """Every migration script defines both upgrade() and downgrade()."""
    cfg = _get_alembic_config()
    script = ScriptDirectory.from_config(cfg)

    for rev in script.walk_revisions():
        module = rev.module
        assert hasattr(module, "upgrade"), f"{rev.revision} missing upgrade()"
        assert hasattr(module, "downgrade"), f"{rev.revision} missing downgrade()"
        assert callable(module.upgrade), f"{rev.revision} upgrade is not callable"
        assert callable(module.downgrade), f"{rev.revision} downgrade is not callable"


@pytest.mark.skipif(
    "sqlite" in os.environ.get("DATABASE_URL", "sqlite"),
    reason="Upgrade/downgrade round-trip requires Postgres (runs in CI)",
)
def test_upgrade_downgrade_roundtrip():
    """Full upgrade to head then downgrade to base. Requires Postgres."""
    from alembic import command
    cfg = _get_alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
