"""
Telegram client (Sprint 9.6).

Thin wrapper over the Telegram Bot sendMessage API. No-ops (returns False) when
credentials aren't configured, so the alert-engine can run safely without them.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

log = logging.getLogger("alert-engine.telegram")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def is_configured() -> bool:
    return bool(BOT_TOKEN and CHAT_ID)


async def send_message(text: str, *, client: Optional[httpx.AsyncClient] = None) -> bool:
    """Send a plain-text message to the configured private channel. Returns success."""
    if not is_configured():
        log.warning("Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID) — skipping send")
        return False

    owns = client is None
    client = client or httpx.AsyncClient(timeout=15.0)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = await client.post(url, json={
            "chat_id": CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        })
        resp.raise_for_status()
        return True
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False
    finally:
        if owns:
            await client.aclose()
