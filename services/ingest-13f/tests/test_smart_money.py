"""Tests for 13F parsing + accumulation value (Sprint 8.7)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from smart_money import parse_13f_infotable, accumulation_signal_value, ACCUMULATION_MAX_VALUE

SAMPLE_INFOTABLE = """<?xml version="1.0"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>ACME THERAPEUTICS INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>00123X105</cusip>
    <value>45000</value>
    <shrsOrPrnAmt><sshPrnamt>1500000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>BLOOM ENERGY CORP</nameOfIssuer>
    <cusip>093712107</cusip>
    <value>120000</value>
    <shrsOrPrnAmt><sshPrnamt>800000</sshPrnamt></shrsOrPrnAmt>
  </infoTable>
</informationTable>"""


def test_parse_infotable_extracts_holdings():
    holdings = parse_13f_infotable(SAMPLE_INFOTABLE)
    assert len(holdings) == 2
    acme = holdings[0]
    assert acme["issuer_name"] == "ACME THERAPEUTICS INC"
    assert acme["cusip"] == "00123X105"
    assert acme["value_usd"] == 45000.0
    assert acme["shares"] == 1500000.0


def test_parse_empty_returns_empty():
    assert parse_13f_infotable("") == []
    assert parse_13f_infotable("<foo>nothing</foo>") == []


def test_parse_handles_namespaced_prefixes():
    xml = """<ns1:informationTable xmlns:ns1="x">
      <ns1:infoTable><ns1:nameOfIssuer>FOO CORP</ns1:nameOfIssuer>
      <ns1:value>1000</ns1:value></ns1:infoTable></ns1:informationTable>"""
    holdings = parse_13f_infotable(xml)
    assert len(holdings) == 1
    assert holdings[0]["issuer_name"] == "FOO CORP"


def test_accumulation_value_favors_small_caps():
    small = accumulation_signal_value(200e6)
    mid = accumulation_signal_value(2e9)
    large = accumulation_signal_value(50e9)
    assert small > mid > large
    # confirmation-only: never exceeds the cap
    assert small <= ACCUMULATION_MAX_VALUE
    assert accumulation_signal_value(None) <= ACCUMULATION_MAX_VALUE
