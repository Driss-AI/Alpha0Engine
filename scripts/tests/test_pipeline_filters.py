"""A one-off debugging switch must not silently gut every scheduled run.

PIPELINE_ONLY / PIPELINE_SKIP live on a cron service. One left behind after a
manual run once caused production to skip universe discovery, prices, SEC, FDA
and news for weeks — scoring 10k names against stale data and exiting 0.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from scripts.run_daily_pipeline import _scoped_step_filter  # noqa: E402


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _yesterday() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("PIPELINE_ONLY", raising=False)
    monkeypatch.delenv("PIPELINE_SKIP", raising=False)


class TestScopedStepFilter:
    def test_unset_is_none(self):
        assert _scoped_step_filter("PIPELINE_ONLY") is None

    def test_empty_is_none(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_ONLY", "   ")
        assert _scoped_step_filter("PIPELINE_ONLY") is None

    def test_undated_value_still_applies(self, monkeypatch):
        """Manual runs keep working — but the caller warns."""
        monkeypatch.setenv("PIPELINE_ONLY", "ingest-trials,screener")
        assert _scoped_step_filter("PIPELINE_ONLY") == "ingest-trials,screener"

    def test_date_scoped_applies_on_its_day(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_ONLY", f"{_today()}:ingest-trials,screener")
        assert _scoped_step_filter("PIPELINE_ONLY") == "ingest-trials,screener"

    def test_date_scoped_self_disarms_the_next_day(self, monkeypatch):
        """This is the whole point: a stale flag stops filtering."""
        monkeypatch.setenv("PIPELINE_ONLY", f"{_yesterday()}:ingest-trials,screener")
        assert _scoped_step_filter("PIPELINE_ONLY") is None

    def test_scope_with_no_steps_is_none(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_SKIP", f"{_today()}:")
        assert _scoped_step_filter("PIPELINE_SKIP") is None

    def test_step_names_are_not_mistaken_for_a_date_scope(self, monkeypatch):
        """A colon that isn't a date must be left alone, not eaten as a scope."""
        monkeypatch.setenv("PIPELINE_SKIP", "not-a-date:ingest-news")
        assert _scoped_step_filter("PIPELINE_SKIP") == "not-a-date:ingest-news"
