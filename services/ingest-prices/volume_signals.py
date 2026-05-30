"""
Volume / price-action signal detection (Sprint 8.8) — pure, testable.

Detects "the market starting to wake up" on a name BEFORE the move completes:
  - volume_awakening: latest volume >= 2x the 30-day average
  - price_breakout:   meaningful 20-day move on elevated volume
  - unusual_options:  placeholder — only emitted if options data is present
"""
from __future__ import annotations

from typing import Any, Optional

VOLUME_AWAKENING_MULT = 2.0      # >= 2x 30d avg volume
BREAKOUT_20D_PCT = 0.20          # +20% over 20 days
BREAKOUT_VOLUME_MULT = 1.5       # on >= 1.5x avg volume


def volume_ratio(volume: Optional[float], avg_volume_30d: Optional[float]) -> Optional[float]:
    if not volume or not avg_volume_30d or avg_volume_30d <= 0:
        return None
    return round(volume / avg_volume_30d, 2)


def detect_volume_signals(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of {signal_type, value, detail} for one latest price record.

    Empty list when nothing notable. `value` is a 0–1 strength.
    """
    out: list[dict[str, Any]] = []
    vr = volume_ratio(record.get("volume"), record.get("avg_volume_30d"))

    if vr is not None and vr >= VOLUME_AWAKENING_MULT:
        # Strength scales with how extreme the spike is (cap at 5x → 1.0).
        strength = min((vr - VOLUME_AWAKENING_MULT) / (5.0 - VOLUME_AWAKENING_MULT), 1.0)
        out.append({
            "signal_type": "volume_awakening",
            "value": round(0.5 + 0.5 * strength, 4),
            "detail": {"volume_ratio": vr},
        })

    chg_20d = record.get("change_20d_pct")
    if (chg_20d is not None and chg_20d >= BREAKOUT_20D_PCT
            and vr is not None and vr >= BREAKOUT_VOLUME_MULT):
        out.append({
            "signal_type": "price_breakout",
            "value": round(min(0.5 + chg_20d, 0.95), 4),
            "detail": {"change_20d_pct": chg_20d, "volume_ratio": vr},
        })

    return out
