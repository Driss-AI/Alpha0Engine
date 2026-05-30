"""
Form 4 Parser
==============
Parses SEC EDGAR Form 4 XML filings to extract insider transactions.
Form 4 structure:
  - ownershipDocument
    - issuer (company CIK, name, ticker)
    - reportingOwner (insider name, title, relationship)
    - nonDerivativeTable (stock transactions)
      - transactionAmounts (shares, price, acquired/disposed)
    - derivativeTable (options/warrants)

We focus on nonDerivativeTable for direct stock buys/sells.
"""
import logging
from typing import Dict, Any, Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


# ── SEC Form 4 transaction code classification (Sprint 8.6) ──────────────────
# The transaction CODE is authoritative — not the acquired/disposed flag (a grant
# is "acquired" but is NOT an open-market purchase). Signal value differs sharply:
#   P  open-market purchase   -> STRONG bullish (insider spending own money)
#   A  grant / award          -> NOT a signal (compensation)
#   M  option exercise        -> WEAK (often just converting options)
#   S  open-market sale        -> risk signal
#   F  shares withheld for tax -> neutral
#   G  gift                    -> neutral
TX_CODE_MEANING = {
    "P": ("Purchase", "open_market_buy"),
    "S": ("Sale", "open_market_sale"),
    "A": ("Grant", "grant"),
    "M": ("OptionExercise", "option_exercise"),
    "F": ("TaxWithholding", "tax"),
    "G": ("Gift", "gift"),
    "C": ("Conversion", "conversion"),
    "D": ("Disposition", "disposition"),
    "X": ("OptionExercise", "option_exercise"),
}


def classify_transaction(tx_code: str, acquired_disposed: str = "") -> dict:
    """Classify a Form 4 transaction by its CODE (Sprint 8.6).

    Returns {type, category, is_open_market_purchase, is_sale, signal_weight}.
    signal_weight: 1.0 open-market buy, 0.3 option exercise, 0.0 grant/neutral,
    -1.0 sale (risk).
    """
    code = (tx_code or "").upper().strip()
    type_label, category = TX_CODE_MEANING.get(code, (code or "Unknown", "other"))

    is_buy = category == "open_market_buy"
    is_sale = category in ("open_market_sale", "disposition")

    if is_buy:
        weight = 1.0
    elif category == "option_exercise":
        weight = 0.3
    elif is_sale:
        weight = -1.0
    else:
        weight = 0.0

    return {
        "type": type_label,
        "category": category,
        "is_open_market_purchase": is_buy,
        "is_sale": is_sale,
        "signal_weight": weight,
    }


def detect_10b5_1(xml_text: str) -> bool:
    """Detect a Rule 10b5-1 trading plan reference (Sprint 8.6).

    10b5-1 sales are pre-scheduled and carry LOWER signal than discretionary
    sales. Indicated by footnote text or the newer <transactionTimeliness>/
    checkbox. We scan the raw XML for the rule reference.
    """
    low = (xml_text or "").lower()
    return "10b5-1" in low or "10b5 1" in low or "rule 10b5" in low


def _text(el, tag: str, default: str = "") -> str:
    """Safely extract text from an XML element."""
    child = el.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    # Also check for .//tag (nested)
    child = el.find(f".//{tag}")
    if child is not None and child.text:
        return child.text.strip()
    return default


def _float(el, tag: str, default: float = 0.0) -> float:
    """Safely extract a float from XML."""
    val = _text(el, tag)
    if val:
        try:
            return float(val.replace(",", ""))
        except ValueError:
            pass
    return default


def parse_form4_xml(xml_text: str) -> Optional[Dict[str, Any]]:
    """
    Parse a Form 4 XML filing into structured transaction data.

    Returns dict with:
      - issuer_cik, issuer_name, issuer_ticker
      - insider_name, insider_title, insider_relationship
      - transactions: list of {type, date, shares, price_per_share, value, acquired_disposed}
      - total_buys, total_sells, net_shares, net_value
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.debug(f"XML parse error: {e}")
        return None

    # ── Issuer info ─────────────────────────────────
    issuer = root.find(".//issuer")
    issuer_cik = _text(issuer, "issuerCik") if issuer is not None else ""
    issuer_name = _text(issuer, "issuerName") if issuer is not None else ""
    issuer_ticker = _text(issuer, "issuerTradingSymbol") if issuer is not None else ""

    # ── Reporting Owner ─────────────────────────────
    owner = root.find(".//reportingOwner")
    insider_name = ""
    insider_title = ""
    insider_relationship = ""

    if owner is not None:
        owner_id = owner.find(".//reportingOwnerId")
        if owner_id is not None:
            insider_name = _text(owner_id, "rptOwnerName")

        rel = owner.find(".//reportingOwnerRelationship")
        if rel is not None:
            if _text(rel, "isDirector") == "1" or _text(rel, "isDirector") == "true":
                insider_relationship = "Director"
            if _text(rel, "isOfficer") == "1" or _text(rel, "isOfficer") == "true":
                insider_title = _text(rel, "officerTitle")
                insider_relationship = "Officer"
            if _text(rel, "isTenPercentOwner") == "1":
                insider_relationship = "10% Owner"

    # ── Non-Derivative Transactions (stock buys/sells) ──
    transactions = []
    nd_table = root.find(".//nonDerivativeTable")

    if nd_table is not None:
        for tx in nd_table.findall(".//nonDerivativeTransaction"):
            tx_coding = tx.find(".//transactionCoding")
            tx_amounts = tx.find(".//transactionAmounts")
            post_amounts = tx.find(".//postTransactionAmounts")

            # Transaction code: P=Purchase, S=Sale, A=Grant, M=Exercise
            tx_code = _text(tx_coding, "transactionCode") if tx_coding is not None else ""

            # Transaction date
            tx_date = _text(tx, "transactionDate/value")
            if not tx_date:
                tx_date = _text(tx, ".//transactionDate")

            # Shares and price
            shares = 0.0
            price = 0.0
            acq_disp = ""

            if tx_amounts is not None:
                shares = _float(tx_amounts, ".//transactionShares/value")
                if shares == 0:
                    shares = _float(tx_amounts, "transactionShares")

                price = _float(tx_amounts, ".//transactionPricePerShare/value")
                if price == 0:
                    price = _float(tx_amounts, "transactionPricePerShare")

                acq_el = tx_amounts.find(".//transactionAcquiredDisposedCode")
                if acq_el is not None:
                    acq_disp = _text(acq_el, "value") or acq_el.text or ""

            # Post-transaction holdings
            shares_after = 0.0
            if post_amounts is not None:
                shares_after = _float(post_amounts, ".//sharesOwnedFollowingTransaction/value")

            # Classify transaction
            # Sprint 8.6: classify by transaction CODE (authoritative), not acq/disp.
            cls = classify_transaction(tx_code, acq_disp)

            value = round(shares * price, 2) if shares > 0 and price > 0 else 0.0

            transactions.append({
                "type": cls["type"],
                "category": cls["category"],
                "is_open_market_purchase": cls["is_open_market_purchase"],
                "is_sale": cls["is_sale"],
                "signal_weight": cls["signal_weight"],
                "code": tx_code,
                "date": tx_date,
                "shares": shares,
                "price_per_share": price,
                "value_usd": value,
                "acquired_disposed": acq_disp,
                "shares_after": shares_after,
            })

    # ── Aggregate ───────────────────────────────────
    is_10b5_1 = detect_10b5_1(xml_text)
    # Only TRUE open-market purchases count as buys (grants/exercises excluded).
    buys = [t for t in transactions if t["is_open_market_purchase"]]
    sells = [t for t in transactions if t["is_sale"]]

    total_buy_shares = sum(t["shares"] for t in buys)
    total_buy_value = sum(t["value_usd"] for t in buys)
    total_sell_shares = sum(t["shares"] for t in sells)
    total_sell_value = sum(t["value_usd"] for t in sells)

    return {
        "issuer_cik": issuer_cik.lstrip("0"),
        "issuer_name": issuer_name,
        "issuer_ticker": issuer_ticker.upper(),
        "insider_name": insider_name,
        "insider_title": insider_title or insider_relationship,
        "insider_relationship": insider_relationship,
        "transactions": transactions,
        "buy_count": len(buys),
        "sell_count": len(sells),
        "total_buy_shares": total_buy_shares,
        "total_buy_value": total_buy_value,
        "total_sell_shares": total_sell_shares,
        "total_sell_value": total_sell_value,
        "net_shares": total_buy_shares - total_sell_shares,
        "net_value": total_buy_value - total_sell_value,
        # Sprint 8.6: only open-market purchases are a real bullish signal.
        "has_open_market_buy": len(buys) > 0,
        "is_10b5_1": is_10b5_1,
    }
