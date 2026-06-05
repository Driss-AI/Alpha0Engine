"""
Bucket classifier (Sprint 9.5) — pure, testable.

Maps the 5-axis vector + red flags into one of five action buckets. The strongest
allowed action is DEEP DIVE / SETUP READY — never "BUY". The human decides.

  NO TOUCH    — ≥1 critical red flag, OR risk so high upside is irrelevant. Avoid.
  PASS        — no edge. Ignore.
  WATCH       — interesting but incomplete; track it.
  DEEP DIVE   — evidence strong enough to warrant manual research now.
  SETUP READY — DEEP DIVE + dated near-term catalyst + price/volume confirmation.
"""
from __future__ import annotations


from .axes import AxisScores

BUCKETS = ["NO_TOUCH", "PASS", "WATCH", "DEEP_DIVE", "SETUP_READY"]

# Display labels (the alert/UI form)
BUCKET_LABELS = {
    "NO_TOUCH": "NO TOUCH",
    "PASS": "PASS",
    "WATCH": "WATCH",
    "DEEP_DIVE": "DEEP DIVE",
    "SETUP_READY": "SETUP READY",
}


def classify_bucket(
    axes: AxisScores,
    *,
    has_critical_flag: bool = False,
    has_dated_catalyst: bool = False,
    lane_live_validated: bool = True,
) -> str:
    """Classify a candidate into an action bucket.

    Rules (evaluated top-down):
      1. critical flag OR risk >= 80           -> NO_TOUCH
      2. opportunity < 35                       -> PASS
      3. SETUP_READY needs: opportunity >= 60, timing >= 70, tradability >= 50,
         risk <= 65, confidence >= 50, a dated catalyst, AND a LIVE-VALIDATED lane
         (Sprint 12 — only a lane proven on live matured alerts may graduate a
         candidate to SETUP_READY. research_validated / unvalidated lanes cap at
         DEEP_DIVE, since a backtest correlation isn't live proof).
      4. DEEP_DIVE needs: opportunity >= 55, confidence >= 45, risk <= 70
      5. otherwise                              -> WATCH
    """
    # 1. Hard disqualifiers
    if has_critical_flag or axes.risk >= 80:
        return "NO_TOUCH"

    # 2. No edge
    if axes.opportunity < 35:
        return "PASS"

    # 3. Setup ready — everything lines up, there's a clock on it, AND the lane
    #    is live-validated.
    if (axes.opportunity >= 60
            and axes.timing >= 70
            and axes.tradability >= 50
            and axes.risk <= 65
            and axes.confidence >= 50
            and has_dated_catalyst
            and lane_live_validated):
        return "SETUP_READY"

    # 4. Deep dive — strong asymmetry + corroboration, but setup not fully confirmed
    if axes.opportunity >= 55 and axes.confidence >= 45 and axes.risk <= 70:
        return "DEEP_DIVE"

    # 5. Default
    return "WATCH"


def bucket_label(bucket: str) -> str:
    return BUCKET_LABELS.get(bucket, bucket)


def is_alertable(bucket: str) -> bool:
    """Only DEEP DIVE and SETUP READY are pushed to Telegram (Sprint 9.6)."""
    return bucket in ("DEEP_DIVE", "SETUP_READY")
