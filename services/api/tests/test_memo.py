"""Tests for the alert memo generator + endpoint (Sprint 13)."""
import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from shared.schemas.alert import Alert
from shared.services.memo import build_memo, render_memo_markdown, memo_summary_lines


def _thesis(with_catalyst=True, with_evidence=True):
    return {
        "lane_id": "L1_AI_INFRA",
        "megatrend": "AI training + inference explosion",
        "bottleneck": "power",
        "exposure": "ACME sits on the power bottleneck of AI infrastructure.",
        "why_now": "ppa_signed dated 2026-08-01; volume 2.4x its 30-day average.",
        "evidence": (
            [{"summary": "20-yr PPA with hyperscaler", "source_url": "https://sec.gov/x"}]
            if with_evidence else []
        ),
        "catalyst_type": "ppa_signed" if with_catalyst else None,
        "catalyst_date": "2026-08-01" if with_catalyst else None,
    }


_AXES = {"opportunity": 82, "risk": 40, "timing": 75, "confidence": 60, "tradability": 55}


# ── pure memo build ─────────────────────────────────────────────────────────

def test_memo_has_all_fields_populated():
    memo = build_memo(
        ticker="ACME", company="Acme Power", lane_name="AI Infrastructure",
        bucket="SETUP_READY", thesis=_thesis(), axes=_AXES,
        red_flags=[], mechanics={"float": 12_000_000, "short_pct_float": 0.22,
                                 "volume_ratio": 2.4},
    )
    # Every field is present...
    expected_keys = [
        "ticker", "company", "lane", "bucket", "why_now", "megatrend",
        "bottleneck", "exposure", "evidence", "red_flags", "axis_scores",
        "price_setup", "float_setup", "what_would_invalidate", "what_to_check_manually",
    ]
    for key in expected_keys:
        assert key in memo, f"missing {key}"
    # ...scalar narrative fields are never blank ("n/a" where genuinely absent)...
    for key in ["ticker", "company", "lane", "bucket", "why_now", "megatrend",
                "bottleneck", "exposure", "price_setup", "float_setup"]:
        assert memo[key] not in (None, ""), f"blank {key}"
    # ...and the two explainability lists always have a backstop entry.
    assert memo["what_would_invalidate"]
    assert memo["what_to_check_manually"]
    assert memo["bucket"] == "SETUP READY"
    assert "2.4x" in memo["price_setup"]
    assert "22%" in memo["float_setup"]


def test_memo_has_evidence_url_and_invalidation():
    """QA gate: ≥1 evidence URL and an explicit invalidation condition."""
    memo = build_memo(
        ticker="ACME", company="Acme", lane_name="AI Infrastructure",
        bucket="DEEP_DIVE", thesis=_thesis(), axes=_AXES,
        red_flags=["atm_offering"], mechanics={},
    )
    urls = [e["source_url"] for e in memo["evidence"] if e["source_url"]]
    assert len(urls) >= 1
    assert len(memo["what_would_invalidate"]) >= 1
    # The catalyst + red flag each produce a concrete invalidation line.
    joined = " ".join(memo["what_would_invalidate"]).lower()
    assert "ppa_signed" in joined and "atm_offering" in joined


def test_memo_absent_fields_become_na_not_blank():
    """No catalyst / no evidence / no mechanics → explicit n/a, still valid."""
    memo = build_memo(
        ticker="XYZ", company=None, lane_name="AI Infrastructure",
        bucket="WATCH", thesis=_thesis(with_catalyst=False, with_evidence=False),
        axes=_AXES, red_flags=[], mechanics={},
    )
    assert memo["company"] == "XYZ"            # falls back to ticker
    assert memo["catalyst"] is None
    assert memo["price_setup"] == "n/a"
    assert "n/a" in memo["float_setup"]
    assert memo["evidence"] == []
    # invalidation + manual checks are always non-empty (backstops)
    assert memo["what_would_invalidate"]
    assert memo["what_to_check_manually"]


def test_render_markdown_and_summary():
    memo = build_memo(
        ticker="ACME", company="Acme", lane_name="AI Infrastructure",
        bucket="SETUP_READY", thesis=_thesis(), axes=_AXES, red_flags=[], mechanics={},
    )
    md = render_memo_markdown(memo)
    assert "# ACME — Acme" in md
    assert "## What would invalidate this" in md
    assert "## What to check manually" in md
    summary = memo_summary_lines(memo)
    assert len(summary) == 2
    assert summary[0].startswith("Would invalidate:")


def test_lane_specific_manual_checks():
    bio = build_memo(ticker="SPRB", company="S", lane_name="Biotech",
                     bucket="DEEP_DIVE",
                     thesis={**_thesis(), "lane_id": "L2_BIOTECH"}, axes=_AXES,
                     red_flags=[], mechanics={})
    assert any("ClinicalTrials.gov" in c for c in bio["what_to_check_manually"])


# ── endpoint ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_alert_memo_endpoint_stored(client: AsyncClient, session: AsyncSession):
    stored = build_memo(
        ticker="BE", company="Bloom", lane_name="AI Infrastructure",
        bucket="SETUP_READY", thesis=_thesis(), axes=_AXES, red_flags=[], mechanics={},
    )
    a = Alert(ticker="BE", lane_id="L1_AI_INFRA", bucket="SETUP_READY",
              composite_score=0.8, opportunity_score=82, risk_score=40, timing_score=75,
              forward_return_30d=0.18, payload={"memo": stored})
    session.add(a)
    await session.commit()

    resp = await client.get(f"/api/v1/alerts/{a.id}/memo")
    assert resp.status_code == 200
    body = resp.json()
    assert body["memo"]["ticker"] == "BE"
    assert body["memo"]["outcome"]["forward_return_30d"] == 0.18   # overlaid live
    assert "# BE — Bloom" in body["rendered"]


@pytest.mark.asyncio
async def test_alert_memo_endpoint_fallback(client: AsyncClient, session: AsyncSession):
    """An alert with no stored memo still yields a valid memo."""
    a = Alert(ticker="VST", lane_id="L1_AI_INFRA", bucket="DEEP_DIVE",
              opportunity_score=70, risk_score=45, why_now="structural only")
    session.add(a)
    await session.commit()

    resp = await client.get(f"/api/v1/alerts/{a.id}/memo")
    assert resp.status_code == 200
    memo = resp.json()["memo"]
    assert memo["ticker"] == "VST"
    assert memo["what_would_invalidate"]      # backstop still present


@pytest.mark.asyncio
async def test_alert_memo_404(client: AsyncClient):
    resp = await client.get("/api/v1/alerts/does-not-exist/memo")
    assert resp.status_code == 404
