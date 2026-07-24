"""
Universe hygiene — which listed securities are even scannable.
==============================================================

The engine hunts one thing: a tiny US operating company whose share price can
multiply off a dated binary catalyst (the SPRB pattern). Whole classes of
tickers in the SEC's `company_tickers.json` can *never* be that, no matter how
they score:

  * warrants, units and rights — derivatives of a SPAC shell, not an operating
    company. A warrant has no float, no trial, no FDA calendar of its own.
  * preferred shares — a different instrument on the same issuer.
  * unsponsored foreign ADRs — the SEC labels these "<Company>/ADR". They're
    thin OTC wrappers on a foreign listing, not a US micro-cap.

Before this filter existed, universe discovery created an Entity for every SEC
ticker, so the screener spent ~2.7h a run scoring things like XRPNW (a SPAC
warrant) and KXHCF (a Kioxia ADR) — and the capped Finnhub price budget was
spent on them instead of on real micro-caps. Excluding them is not a scoring
opinion; it's a statement about what the instrument *is*.

`entity_type` is the universe gate used by ingest-prices, fundamentals and the
screener (all select `entity_type == "public"`), so excluded securities are
recorded with EXCLUDED_ENTITY_TYPE and simply never picked up.
"""
from __future__ import annotations

import re

# entity_type given to securities that exist but must never be scanned.
EXCLUDED_ENTITY_TYPE = "excluded_security"
SCANNABLE_ENTITY_TYPE = "public"

# NYSE/NYSE-American style class suffixes, e.g. PEW-WT, BRK.A, XYZ-UN.
_SUFFIX_RE = re.compile(r"[-.]([A-Z]{1,2})$")
_SUFFIX_REASONS = {
    "WT": "warrant",
    "WS": "warrant",
    "W": "warrant",
    "U": "unit",
    "UN": "unit",
    "R": "right",
    "RT": "right",
    "P": "preferred",
    "PR": "preferred",
}

# Nasdaq 5th-letter convention: on a 5-character Nasdaq symbol the final letter
# identifies the security class. W/U/R are reserved by the exchange for
# warrants/units/rights, so a 5-letter common stock never ends in them.
_FIFTH_LETTER_REASONS = {
    "W": "warrant",
    "U": "unit",
    "R": "right",
}

# The SEC titles unsponsored foreign depositary receipts with a "/ADR" suffix.
_ADR_NAME_MARKERS = ("/adr", "/ads")


def classify_security(ticker: str | None, company_name: str | None = None) -> str:
    """Return "common" for a scannable operating-company share, else a reason.

    Reasons: "warrant" | "unit" | "right" | "preferred" | "foreign_adr" |
    "invalid_ticker".
    """
    if not ticker:
        return "invalid_ticker"
    sym = ticker.strip().upper()
    if not sym or len(sym) > 10:
        return "invalid_ticker"

    # The SEC's own "/ADR" labelling is the most reliable ADR signal there is.
    name = (company_name or "").lower()
    if any(marker in name for marker in _ADR_NAME_MARKERS):
        return "foreign_adr"

    # Explicit class suffix (NYSE style).
    m = _SUFFIX_RE.search(sym)
    if m:
        reason = _SUFFIX_REASONS.get(m.group(1))
        if reason:
            return reason

    # Nasdaq 5th-letter convention — plain 5-letter symbols only.
    if len(sym) == 5 and sym.isalpha():
        reason = _FIFTH_LETTER_REASONS.get(sym[-1])
        if reason:
            return reason

    return "common"


def is_scannable(ticker: str | None, company_name: str | None = None) -> bool:
    """True when this security can plausibly be a micro-cap explosion candidate."""
    return classify_security(ticker, company_name) == "common"


def entity_type_for(ticker: str | None, company_name: str | None = None) -> str:
    """The `entity_type` a discovered security should be stored with."""
    return SCANNABLE_ENTITY_TYPE if is_scannable(ticker, company_name) else EXCLUDED_ENTITY_TYPE
