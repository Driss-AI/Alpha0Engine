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
            if tx_code == "P" or acq_disp.upper() == "A":
                tx_type = "Purchase"
            elif tx_code == "S" or acq_disp.upper() == "D":
                tx_type = "Sale"
            elif tx_code == "A":
                tx_type = "Grant"
            elif tx_code == "M":
                tx_type = "OptionExercise"
            else:
                tx_type = tx_code or "Unknown"

            value = round(shares * price, 2) if shares > 0 and price > 0 else 0.0

            transactions.append({
                "type": tx_type,
                "code": tx_code,
                "date": tx_date,
                "shares": shares,
                "price_per_share": price,
                "value_usd": value,
                "acquired_disposed": acq_disp,
                "shares_after": shares_after,
            })

    # ── Aggregate ───────────────────────────────────
    buys = [t for t in transactions if t["type"] == "Purchase"]
    sells = [t for t in transactions if t["type"] == "Sale"]

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
    }
