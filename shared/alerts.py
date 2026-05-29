"""
Alert Webhooks — Discord/Slack notifications for critical events.

Supports:
- Ingest failure >1hr
- DLQ depth >10
- Brain 0 candidates for 3+ days
- Custom alerts

Configuration via environment variables:
    ALERT_WEBHOOK_URL — Discord or Slack webhook URL
    ALERT_CHANNEL — optional channel override (Slack only)
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("alpha0.alerts")

WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL", "")
ALERT_CHANNEL = os.environ.get("ALERT_CHANNEL", "")

SEVERITY_COLORS = {
    "critical": 0xFF0000,  # Red
    "warning": 0xF5A623,   # Amber
    "info": 0x4B9EFF,      # Blue
    "resolved": 0x00E87A,  # Green
}


def _is_discord(url: str) -> bool:
    return "discord.com" in url or "discordapp.com" in url


def _is_slack(url: str) -> bool:
    return "hooks.slack.com" in url


async def send_alert(
    title: str,
    message: str,
    severity: str = "warning",
    fields: Optional[dict] = None,
    webhook_url: Optional[str] = None,
) -> bool:
    """Send an alert to Discord or Slack. Returns True on success."""
    url = webhook_url or WEBHOOK_URL
    if not url:
        logger.warning(f"Alert not sent (no webhook URL): {title}")
        return False

    try:
        if _is_discord(url):
            return await _send_discord(url, title, message, severity, fields)
        elif _is_slack(url):
            return await _send_slack(url, title, message, severity, fields)
        else:
            logger.warning(f"Unknown webhook type for URL, attempting generic POST")
            return await _send_generic(url, title, message, severity, fields)
    except Exception as e:
        logger.error(f"Failed to send alert: {e}")
        return False


async def _send_discord(
    url: str, title: str, message: str, severity: str, fields: Optional[dict]
) -> bool:
    color = SEVERITY_COLORS.get(severity, 0xFFFFFF)
    embed = {
        "title": f"{'🚨' if severity == 'critical' else '⚠️' if severity == 'warning' else 'ℹ️'} {title}",
        "description": message,
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "Alpha0Engine Alerts"},
    }
    if fields:
        embed["fields"] = [
            {"name": k, "value": str(v), "inline": True}
            for k, v in fields.items()
        ]

    payload = {"embeds": [embed]}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code in (200, 204):
            logger.info(f"Discord alert sent: {title}")
            return True
        logger.error(f"Discord webhook failed: {resp.status_code} {resp.text}")
        return False


async def _send_slack(
    url: str, title: str, message: str, severity: str, fields: Optional[dict]
) -> bool:
    color_hex = f"#{SEVERITY_COLORS.get(severity, 0xFFFFFF):06x}"
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{title}*\n{message}"},
        }
    ]
    if fields:
        field_blocks = [
            {"type": "mrkdwn", "text": f"*{k}:* {v}"}
            for k, v in fields.items()
        ]
        blocks.append({"type": "section", "fields": field_blocks})

    payload = {
        "attachments": [{
            "color": color_hex,
            "blocks": blocks,
        }],
    }
    if ALERT_CHANNEL:
        payload["channel"] = ALERT_CHANNEL

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code == 200:
            logger.info(f"Slack alert sent: {title}")
            return True
        logger.error(f"Slack webhook failed: {resp.status_code} {resp.text}")
        return False


async def _send_generic(
    url: str, title: str, message: str, severity: str, fields: Optional[dict]
) -> bool:
    payload = {
        "title": title,
        "message": message,
        "severity": severity,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": fields or {},
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        return resp.status_code < 300


# ── Pre-built alert functions ────────────────────────────────────

async def alert_ingest_failure(service_name: str, hours_since_success: float, error: str = ""):
    await send_alert(
        title=f"Ingest Failure: {service_name}",
        message=f"No successful ingest run for **{hours_since_success:.1f} hours**.\n{error}",
        severity="critical" if hours_since_success > 4 else "warning",
        fields={
            "Service": service_name,
            "Hours since success": f"{hours_since_success:.1f}",
        },
    )


async def alert_dlq_depth(depth: int, stream: str = "alpha:stream:dlq"):
    await send_alert(
        title="DLQ Depth Warning",
        message=f"Dead-letter queue has **{depth}** unprocessed messages.",
        severity="critical" if depth > 50 else "warning",
        fields={
            "Stream": stream,
            "Depth": str(depth),
        },
    )


async def alert_brain_no_candidates(days_without: int):
    await send_alert(
        title="Brain: Zero Candidates",
        message=f"Brain has produced **0 picks** for the last **{days_without} days**.",
        severity="warning",
        fields={"Days without picks": str(days_without)},
    )


async def alert_scoring_anomaly(details: str):
    await send_alert(
        title="Scoring Anomaly Detected",
        message=details,
        severity="warning",
    )
