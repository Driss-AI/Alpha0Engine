"""
Lane tagging for news (Sprint 8.5)

News items carry no market cap, so we can't use the full `match_lanes` universe
filter. Instead we tag by keyword match against each lane and detect high-signal
catalyst phrases that warrant a `news_catalyst` signal.
"""
from __future__ import annotations

from typing import Any

from shared.lanes import ALL_LANES

# Minimum keyword-density score to tag a news item with a lane.
NEWS_LANE_THRESHOLD = 0.04

# High-signal phrases per lane → these escalate a news item to a catalyst.
HIGH_SIGNAL_PHRASES = {
    "L1_AI_INFRA": [
        "ppa signed", "power purchase agreement", "gpu hosting", "data center lease",
        "interconnection approval", "hyperscaler", "gpu order", "capacity agreement",
    ],
    "L2_BIOTECH": [
        "adcom", "advisory committee", "phase 3 readout", "topline data", "pdufa",
        "fda approval", "complete response letter", "breakthrough therapy",
    ],
}


def tag_news_lanes(title: str, summary: str) -> list[dict[str, Any]]:
    """Return lane tags for a news item.

    Each tag: {lane_id, score, bottlenecks: [...], high_signal: bool, phrases: [...]}.
    Empty list when the item matches no lane.
    """
    text = f"{title} {summary}".lower()
    tags: list[dict[str, Any]] = []
    for lane in ALL_LANES:
        score = lane.match_score(text)
        if score < NEWS_LANE_THRESHOLD:
            continue
        phrases = [p for p in HIGH_SIGNAL_PHRASES.get(lane.lane_id, []) if p in text]
        tags.append({
            "lane_id": lane.lane_id,
            "score": score,
            "bottlenecks": lane.matched_bottlenecks(text),
            "high_signal": bool(phrases),
            "phrases": phrases,
        })
    tags.sort(key=lambda t: t["score"], reverse=True)
    return tags
