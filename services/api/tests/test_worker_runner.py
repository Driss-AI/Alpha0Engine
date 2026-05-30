"""Tests for shared.worker_runner count coercion (regression: brain crash)."""
from shared.worker_runner import _coerce_count, _apply_return


class _Run:
    def __init__(self):
        self.records_processed = 0
        self.records_skipped = 0
        self.errors = 0
        self.run_metadata = {}


class _Tracker:
    def __init__(self):
        self.run = _Run()


def test_coerce_count_handles_list():
    # brain returns errors as a LIST of error entries — must become a count
    assert _coerce_count(["e1", "e2", "e3"]) == 3
    assert _coerce_count([]) == 0


def test_coerce_count_handles_numbers_and_junk():
    assert _coerce_count(5) == 5
    assert _coerce_count(2.0) == 2
    assert _coerce_count(True) == 1
    assert _coerce_count(None) == 0
    assert _coerce_count("nope") == 0


def test_apply_return_with_brain_shape_does_not_crash():
    # Regression: brain's stats dict has errors=list; previously int(list) crashed.
    t = _Tracker()
    _apply_return(t, {"threshold_passed": 0, "analyzed": 0,
                      "errors": ["a", "b", "c", "d", "e", "f"]})
    assert t.run.errors == 6


def test_apply_return_with_standard_shape():
    t = _Tracker()
    _apply_return(t, {"records_processed": 10, "records_skipped": 2, "errors": 1,
                      "metadata": {"k": "v"}})
    assert t.run.records_processed == 10
    assert t.run.records_skipped == 2
    assert t.run.errors == 1
    assert t.run.run_metadata == {"k": "v"}


def test_apply_return_ignores_non_dict():
    t = _Tracker()
    _apply_return(t, None)
    _apply_return(t, "string")
    assert t.run.records_processed == 0
