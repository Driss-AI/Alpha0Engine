"""
Watchlist sentinel — daily checkups on followed stocks.
=======================================================
Runs after alert dispatch. For every hearted watchlist ticker it answers one
question: WHAT CHANGED since the last checkup? If something did, it sends a
short Telegram checkup (with an analyst take when it's material); if nothing
did, it stays silent — same silence-is-golden rule as discovery.

Exit-side escalation: discovery whispers, invalidation shouts. A newly
appeared critical red flag (ATM filing, going concern, delisting notice…)
always fires, prefixed as an alarm, and always gets an analyst take.

State: each checkup is recorded in the `alerts` table with bucket="CHECKUP";
the payload carries the compared state, so the next run diffs against it
without any new table.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger("alert-engine.sentinel")

MATERIAL_SCORE_MOVE = 0.05     # composite delta worth mentioning
CATALYST_HORIZON_DAYS = 60     # upcoming catalysts to surface in checkups
ANALYST_SCORE_MOVE = 0.10      # composite delta that earns an analyst take


# ── Pure change detection (testable without a DB) ───────────────────────────

def detect_changes(prev: dict[str, Any], curr: dict[str, Any]) -> dict[str, Any]:
    """Diff two checkup states.

    State shape (both sides): {composite_score, bucket, red_flags: [..],
    critical_flags: [..], catalyst_date: iso|None, signal_count}.
    Returns {changes: [str], escalate: bool, material: bool}.
    """
    changes: list[str] = []
    escalate = False

    prev_crit = set(prev.get("critical_flags") or [])
    curr_crit = set(curr.get("critical_flags") or [])
    new_crit = curr_crit - prev_crit
    if new_crit:
        changes.append("🚨 CRITICAL: " + ", ".join(sorted(new_crit)))
        escalate = True

    new_flags = (set(curr.get("red_flags") or []) - set(prev.get("red_flags") or [])) - new_crit
    if new_flags:
        changes.append("new red flags: " + ", ".join(sorted(new_flags)))

    prev_bucket, curr_bucket = prev.get("bucket"), curr.get("bucket")
    if prev_bucket and curr_bucket and prev_bucket != curr_bucket:
        changes.append(f"bucket {prev_bucket} → {curr_bucket}")
        if curr_bucket == "NO_TOUCH":
            escalate = True

    ps, cs = prev.get("composite_score"), curr.get("composite_score")
    score_move = abs((cs or 0) - (ps or 0)) if (ps is not None and cs is not None) else 0.0
    if score_move >= MATERIAL_SCORE_MOVE:
        direction = "↑" if (cs or 0) >= (ps or 0) else "↓"
        changes.append(f"score {direction} {ps:.3f} → {cs:.3f}")

    prev_cat, curr_cat = prev.get("catalyst_date"), curr.get("catalyst_date")
    if curr_cat != prev_cat:
        if curr_cat and not prev_cat:
            changes.append(f"catalyst dated: {curr_cat}")
        elif prev_cat and not curr_cat:
            changes.append(f"catalyst date removed (was {prev_cat})")
        else:
            changes.append(f"catalyst moved {prev_cat} → {curr_cat}")

    new_signals = (curr.get("signal_count") or 0) - (prev.get("signal_count") or 0)
    if new_signals > 0:
        changes.append(f"{new_signals} new signal(s)")

    return {
        "changes": changes,
        "escalate": escalate,
        "material": escalate or score_move >= ANALYST_SCORE_MOVE or bool(new_crit),
    }


def format_checkup(
    ticker: str,
    changes: list[str],
    *,
    escalate: bool,
    bucket: Optional[str],
    catalyst_line: Optional[str],
    take_lines: Optional[list[str]] = None,
) -> str:
    header = f"🔔 EXIT ALARM — {ticker}" if escalate else f"🩺 Checkup — {ticker}"
    lines = [header, f"status: {bucket or '—'}"]
    lines += [f"• {c}" for c in changes]
    if catalyst_line:
        lines.append(catalyst_line)
    if take_lines:
        lines.append("")
        lines += take_lines
    return "\n".join(lines)


# ── DB-facing runner ────────────────────────────────────────────────────────

async def _current_state(session: AsyncSession, ticker: str) -> Optional[dict[str, Any]]:
    """Assemble today's comparable state for a ticker from the scoring tables."""
    from shared.schemas.equity_screen import EquityScreen
    from shared.schemas.signals import Signal
    from shared.schemas.catalyst_event import CatalystEvent

    screen = (await session.exec(
        select(EquityScreen).where(EquityScreen.ticker == ticker)
    )).first()
    if screen is None:
        return None

    raw = screen.raw_data or {}
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    recent_signals = []
    if screen.entity_id:
        rows = (await session.exec(
            select(Signal).where(
                Signal.entity_id == screen.entity_id,
                Signal.signal_date >= cutoff,
            ).limit(20)
        )).all()
        recent_signals = [
            {"signal_type": s.signal_type, "notes": (s.notes or "")[:120]}
            for s in rows if s.signal_type != "float_snapshot"
        ]

    today = date.today()
    catalyst_date = None
    catalyst_title = None
    cat_rows = (await session.exec(
        select(CatalystEvent).where(
            CatalystEvent.ticker == ticker,
            CatalystEvent.status == "upcoming",
        ).order_by(CatalystEvent.expected_date)
    )).all()
    for c in cat_rows:
        if c.expected_date and c.expected_date >= today:
            catalyst_date = c.expected_date.isoformat()
            catalyst_title = c.title
            break

    signal_count = 0
    if screen.entity_id:
        signal_count = len((await session.exec(
            select(Signal.id).where(Signal.entity_id == screen.entity_id)
        )).all())

    return {
        "composite_score": screen.composite_score,
        "bucket": screen.bucket,
        "red_flags": raw.get("red_flags", []),
        "critical_flags": raw.get("critical_flags", []),
        "catalyst_date": catalyst_date,
        "catalyst_title": catalyst_title,
        "signal_count": signal_count,
        # extras for messages/dossiers (not diffed)
        "entity_id": screen.entity_id,
        "company_name": screen.company_name,
        "lane_id": screen.best_lane_id,
        "axes": raw.get("axes", {}),
        "recent_signals": recent_signals,
    }


async def _last_checkup_state(session: AsyncSession, ticker: str) -> dict[str, Any]:
    from shared.schemas.alert import Alert
    row = (await session.exec(
        select(Alert).where(
            Alert.ticker == ticker,
            Alert.bucket == "CHECKUP",
        ).order_by(Alert.sent_at.desc())
    )).first()
    return (row.payload or {}).get("state", {}) if row else {}


_DIFF_KEYS = ("composite_score", "bucket", "red_flags", "critical_flags",
              "catalyst_date", "signal_count")


async def run_sentinel() -> dict[str, Any]:
    """Check every followed ticker; message only on change. Returns stats."""
    from shared.clients.postgres import AsyncSessionLocal
    from shared.schemas.watchlist import UserWatchlist
    from shared.schemas.alert import Alert
    import telegram_client
    import analyst

    checked = 0
    messaged = 0
    escalated = 0

    async with AsyncSessionLocal() as session:
        followed = (await session.exec(
            select(UserWatchlist).where(UserWatchlist.hearted == True)  # noqa: E712
        )).all()
        logger.info(f"SENTINEL — {len(followed)} followed ticker(s)")

        for item in followed:
            ticker = item.ticker.upper()
            curr = await _current_state(session, ticker)
            if curr is None:
                logger.info(f"  {ticker}: not screened yet — skipping")
                continue
            checked += 1

            prev = await _last_checkup_state(session, ticker)
            diff = detect_changes(prev, curr)
            is_first = not prev
            if not diff["changes"] and not is_first:
                continue  # silence is golden

            if is_first and not diff["changes"]:
                diff["changes"] = ["now under sentinel watch"]

            catalyst_line = None
            if curr.get("catalyst_date"):
                days = (date.fromisoformat(curr["catalyst_date"]) - date.today()).days
                catalyst_line = (f"📅 {curr.get('catalyst_title') or 'catalyst'} "
                                 f"in {days}d ({curr['catalyst_date']})")

            take_lines = None
            if diff["material"]:
                take = analyst.analyst_take(analyst.build_dossier(
                    ticker=ticker,
                    company=curr.get("company_name"),
                    lane_name=curr.get("lane_id"),
                    bucket=curr.get("bucket"),
                    thesis=None,
                    axes=curr.get("axes"),
                    red_flags=curr.get("red_flags"),
                    mechanics=None,
                    catalysts=[{"date": curr.get("catalyst_date"),
                                "title": curr.get("catalyst_title")}]
                              if curr.get("catalyst_date") else [],
                    recent_signals=curr.get("recent_signals"),
                    changes=diff["changes"],
                ))
                if take:
                    take_lines = analyst.format_take_lines(take)

            message = format_checkup(
                ticker, diff["changes"],
                escalate=diff["escalate"],
                bucket=curr.get("bucket"),
                catalyst_line=catalyst_line,
                take_lines=take_lines,
            )
            delivered = await telegram_client.send_message(message)
            session.add(Alert(
                ticker=ticker,
                entity_id=curr.get("entity_id"),
                lane_id=curr.get("lane_id"),
                bucket="CHECKUP",
                composite_score=curr.get("composite_score"),
                why_now="; ".join(diff["changes"])[:500],
                message=message,
                delivered=delivered,
                payload={"state": {k: curr.get(k) for k in _DIFF_KEYS},
                         "escalate": diff["escalate"]},
            ))
            messaged += 1
            if diff["escalate"]:
                escalated += 1
                logger.info(f"  🔔 {ticker}: ESCALATED — {diff['changes']}")
            else:
                logger.info(f"  🩺 {ticker}: checkup sent — {diff['changes']}")

        await session.commit()

    logger.info(f"SENTINEL COMPLETE — {checked} checked, {messaged} messaged, "
                f"{escalated} escalated")
    return {"checked": checked, "messaged": messaged, "escalated": escalated}
