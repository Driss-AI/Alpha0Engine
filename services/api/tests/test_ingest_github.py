"""
GitHub Archive ingest failure simulation tests.
Verifies the client handles rate limits, 404s, and corrupt data
gracefully — no crashes, proper logging.
"""
import sys
import os
import gzip
import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
import requests

GITHUB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ingest-github"))
if GITHUB_DIR not in sys.path:
    sys.path.insert(0, GITHUB_DIR)

from gh_archive_client import GitHubArchiveClient


def _mock_response(status_code=200, content=b"", raise_exc=None):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.content = content
    if raise_exc:
        resp.raise_for_status.side_effect = raise_exc
    else:
        resp.raise_for_status.return_value = None
    return resp


def _make_gz_content(events: list[dict]) -> bytes:
    lines = "\n".join(json.dumps(e) for e in events)
    return gzip.compress(lines.encode("utf-8"))


class TestGitHubRateLimit:
    def test_rate_limit_403_returns_empty(self):
        client = GitHubArchiveClient()
        from datetime import datetime
        resp = _mock_response(403, raise_exc=requests.HTTPError(
            response=MagicMock(status_code=403)
        ))
        with patch.object(client.session, "get", return_value=resp):
            events = client.fetch_hour(datetime(2026, 5, 28, 12))
        assert events == []

    def test_rate_limit_429_returns_empty(self):
        client = GitHubArchiveClient()
        from datetime import datetime
        resp = _mock_response(429, raise_exc=requests.HTTPError(
            response=MagicMock(status_code=429)
        ))
        with patch.object(client.session, "get", return_value=resp):
            events = client.fetch_hour(datetime(2026, 5, 28, 12))
        assert events == []


class TestGitHubErrors:
    def test_404_returns_empty(self):
        client = GitHubArchiveClient()
        from datetime import datetime
        resp = _mock_response(404, raise_exc=requests.HTTPError(
            response=MagicMock(status_code=404)
        ))
        with patch.object(client.session, "get", return_value=resp):
            events = client.fetch_hour(datetime(2026, 5, 28, 23))
        assert events == []

    def test_timeout_returns_empty(self):
        client = GitHubArchiveClient()
        from datetime import datetime
        with patch.object(client.session, "get", side_effect=requests.Timeout("timed out")):
            events = client.fetch_hour(datetime(2026, 5, 28, 12))
        assert events == []

    def test_connection_error_returns_empty(self):
        client = GitHubArchiveClient()
        from datetime import datetime
        with patch.object(client.session, "get", side_effect=requests.ConnectionError()):
            events = client.fetch_hour(datetime(2026, 5, 28, 12))
        assert events == []

    def test_corrupt_gzip_returns_empty(self):
        client = GitHubArchiveClient()
        from datetime import datetime
        resp = _mock_response(200, content=b"not gzip data")
        with patch.object(client.session, "get", return_value=resp):
            events = client.fetch_hour(datetime(2026, 5, 28, 12))
        assert events == []


class TestGitHubHappyPath:
    def test_valid_events_parsed(self):
        client = GitHubArchiveClient()
        from datetime import datetime
        events_data = [
            {"type": "PushEvent", "repo": {"name": "testorg/repo1"}},
            {"type": "WatchEvent", "repo": {"name": "testorg/repo2"}},
            {"type": "IssueCommentEvent", "repo": {"name": "testorg/repo3"}},
        ]
        content = _make_gz_content(events_data)
        resp = _mock_response(200, content=content)
        with patch.object(client.session, "get", return_value=resp):
            events = client.fetch_hour(datetime(2026, 5, 28, 12))
        assert len(events) == 3

    def test_filter_relevant_by_org(self):
        client = GitHubArchiveClient()
        events = [
            {"type": "PushEvent", "repo": {"name": "tracked-org/repo1"}},
            {"type": "PushEvent", "repo": {"name": "other-org/repo2"}},
            {"type": "WatchEvent", "repo": {"name": "tracked-org/repo3"}},
        ]
        tracked = {"tracked-org": "ent-1"}
        relevant = client.filter_relevant(events, tracked)
        assert len(relevant) == 2
        assert all(r["_tracked_org"] == "tracked-org" for r in relevant)

    def test_filter_skips_untracked_event_types(self):
        client = GitHubArchiveClient()
        events = [
            {"type": "IssueCommentEvent", "repo": {"name": "tracked-org/repo1"}},
        ]
        tracked = {"tracked-org": "ent-1"}
        relevant = client.filter_relevant(events, tracked)
        assert len(relevant) == 0

    def test_malformed_json_lines_skipped(self):
        client = GitHubArchiveClient()
        from datetime import datetime
        raw = '{"type":"PushEvent","repo":{"name":"org/r"}}\nnot json\n{"type":"WatchEvent","repo":{"name":"org/r2"}}'
        content = gzip.compress(raw.encode("utf-8"))
        resp = _mock_response(200, content=content)
        with patch.object(client.session, "get", return_value=resp):
            events = client.fetch_hour(datetime(2026, 5, 28, 12))
        assert len(events) == 2
