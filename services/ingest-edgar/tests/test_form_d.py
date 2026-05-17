import pytest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from form_d_parser import parse_form_d

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/document/formd/formD">
  <issuerInformation>
    <issuerName>Acme AI Corp</issuerName>
    <stateOfIncorporation>DE</stateOfIncorporation>
    <industryGroup>Technology</industryGroup>
  </issuerInformation>
  <offeringInformation>
    <totalOfferingAmount>10000000</totalOfferingAmount>
    <totalAmountSold>5000000</totalAmountSold>
    <minimumInvestmentAccepted>250000</minimumInvestmentAccepted>
    <totalNumberAlreadyInvested>4</totalNumberAlreadyInvested>
    <dateOfFirstSale>2026-05-01</dateOfFirstSale>
  </offeringInformation>
  <relatedPersonsList>
    <relatedPersonInfo>
      <relatedPersonFirstName>Jane</relatedPersonFirstName>
      <relatedPersonLastName>Smith</relatedPersonLastName>
      <relatedPersonRelationship>Executive Officer</relatedPersonRelationship>
    </relatedPersonInfo>
  </relatedPersonsList>
</edgarSubmission>"""


def test_parse_basic():
    meta = {"accession_number": "0001234567", "cik": "0000999999", "file_date": "2026-05-15", "company_name": "Acme AI Corp"}
    result = parse_form_d(SAMPLE_XML, meta)
    assert result is not None
    assert result["company_name"] == "Acme AI Corp"
    assert result["total_offering_amount"] == 10_000_000.0
    assert result["total_amount_sold"] == 5_000_000.0
    assert len(result["related_persons"]) == 1
    assert result["related_persons"][0]["name"] == "Jane Smith"


def test_parse_invalid_xml():
    assert parse_form_d("not valid xml", {"accession_number": "bad"}) is None
