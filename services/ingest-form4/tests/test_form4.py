"""
Tests — Form 4 Insider Transaction Ingestion
================================================
Tests XML parsing, transaction classification, and signal value computation.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from form4_parser import parse_form4_xml

# ── Sample Form 4 XML (realistic structure) ─────────────────
SAMPLE_BUY_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer>
    <issuerCik>0001234567</issuerCik>
    <issuerName>TestPharma Inc</issuerName>
    <issuerTradingSymbol>TPHR</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0009876543</rptOwnerCik>
      <rptOwnerName>John Smith</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>0</isDirector>
      <isOfficer>1</isOfficer>
      <officerTitle>CEO</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-05-15</value></transactionDate>
      <transactionCoding>
        <transactionCode>P</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>50000</value></transactionShares>
        <transactionPricePerShare><value>8.50</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>150000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""

SAMPLE_SELL_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer>
    <issuerCik>0001234567</issuerCik>
    <issuerName>BigTech Corp</issuerName>
    <issuerTradingSymbol>BGTK</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerName>Jane Doe</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
      <isOfficer>0</isOfficer>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-05-10</value></transactionDate>
      <transactionCoding>
        <transactionCode>S</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>10000</value></transactionShares>
        <transactionPricePerShare><value>150.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>90000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""

SAMPLE_MULTI_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer>
    <issuerCik>0005555555</issuerCik>
    <issuerName>MixedCo Inc</issuerName>
    <issuerTradingSymbol>MXCO</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerName>Bob CFO</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isOfficer>1</isOfficer>
      <officerTitle>CFO</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-05-01</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>5000</value></transactionShares>
        <transactionPricePerShare><value>12.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>15000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-05-05</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>2000</value></transactionShares>
        <transactionPricePerShare><value>14.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>13000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


# ═══════════════════════════════════════════════════════════
# Parser Tests
# ═══════════════════════════════════════════════════════════
class TestForm4Parser:
    def test_parse_buy(self):
        result = parse_form4_xml(SAMPLE_BUY_XML)
        assert result is not None
        assert result["issuer_ticker"] == "TPHR"
        assert result["issuer_cik"] == "1234567"
        assert result["insider_name"] == "John Smith"
        assert result["insider_title"] == "CEO"
        assert result["insider_relationship"] == "Officer"
        assert result["buy_count"] == 1
        assert result["sell_count"] == 0
        assert result["total_buy_shares"] == 50000
        assert result["total_buy_value"] == 425000.0  # 50000 * 8.50

    def test_parse_sell(self):
        result = parse_form4_xml(SAMPLE_SELL_XML)
        assert result is not None
        assert result["issuer_ticker"] == "BGTK"
        assert result["insider_name"] == "Jane Doe"
        assert result["insider_relationship"] == "Director"
        assert result["buy_count"] == 0
        assert result["sell_count"] == 1
        assert result["total_sell_shares"] == 10000
        assert result["total_sell_value"] == 1500000.0

    def test_parse_multi_transactions(self):
        result = parse_form4_xml(SAMPLE_MULTI_XML)
        assert result is not None
        assert result["buy_count"] == 1
        assert result["sell_count"] == 1
        assert result["total_buy_shares"] == 5000
        assert result["total_sell_shares"] == 2000
        assert result["net_shares"] == 3000  # Net buyer
        assert result["insider_title"] == "CFO"

    def test_parse_invalid_xml(self):
        result = parse_form4_xml("not xml at all")
        assert result is None

    def test_parse_empty_xml(self):
        result = parse_form4_xml("<ownershipDocument></ownershipDocument>")
        assert result is not None
        assert result["buy_count"] == 0
        assert result["sell_count"] == 0

    def test_shares_after(self):
        result = parse_form4_xml(SAMPLE_BUY_XML)
        assert result["transactions"][0]["shares_after"] == 150000

    def test_transaction_date(self):
        result = parse_form4_xml(SAMPLE_BUY_XML)
        assert result["transactions"][0]["date"] == "2026-05-15"


# ═══════════════════════════════════════════════════════════
# Signal Value Tests
# ═══════════════════════════════════════════════════════════
class TestSignalValue:
    def test_large_buy_officer(self):
        from main import _compute_signal_value
        parsed = {
            "buy_count": 1, "sell_count": 0,
            "total_buy_value": 600_000, "total_sell_value": 0,
            "net_value": 600_000,
            "insider_relationship": "Officer",
        }
        value = _compute_signal_value(parsed)
        assert value >= 0.8

    def test_small_buy(self):
        from main import _compute_signal_value
        parsed = {
            "buy_count": 1, "sell_count": 0,
            "total_buy_value": 10_000, "total_sell_value": 0,
            "net_value": 10_000,
            "insider_relationship": "Director",
        }
        value = _compute_signal_value(parsed)
        assert 0.6 <= value <= 0.75

    def test_pure_sell(self):
        from main import _compute_signal_value
        parsed = {
            "buy_count": 0, "sell_count": 1,
            "total_buy_value": 0, "total_sell_value": 500_000,
            "net_value": -500_000,
            "insider_relationship": "Officer",
        }
        value = _compute_signal_value(parsed)
        assert value == 0.25  # Mildly bearish

    def test_net_buyer(self):
        from main import _compute_signal_value
        parsed = {
            "buy_count": 2, "sell_count": 1,
            "total_buy_value": 100_000, "total_sell_value": 30_000,
            "net_value": 70_000,
            "insider_relationship": "Officer",
        }
        value = _compute_signal_value(parsed)
        assert value == 0.55


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
