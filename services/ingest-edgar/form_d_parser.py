"""
Form D XML Parser
=================
Parses SEC Form D XML into structured signal dict.
Key fields: company, state, industry, offering amounts, dates, exemption type.
"""
import logging
from typing import Dict, Any, Optional
from lxml import etree

log = logging.getLogger(__name__)


def parse_form_d(xml_content: str, filing_meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        root = etree.fromstring(xml_content.encode("utf-8"))
        ns = _ns(root)
        return {
            "accession_number": filing_meta.get("accession_number", ""),
            "cik": filing_meta.get("cik", ""),
            "file_date": filing_meta.get("file_date", ""),
            "entity_id": "UNRESOLVED",
            "company_name": _txt(root, ns, "issuerName") or filing_meta.get("company_name", ""),
            "state_of_incorporation": _txt(root, ns, "stateOfIncorporation"),
            "industry_group": _txt(root, ns, "industryGroup"),
            "total_offering_amount": _flt(root, ns, "totalOfferingAmount"),
            "total_amount_sold": _flt(root, ns, "totalAmountSold"),
            "min_investment": _flt(root, ns, "minimumInvestmentAccepted"),
            "investors_already": _int(root, ns, "totalNumberAlreadyInvested"),
            "date_of_first_sale": _txt(root, ns, "dateOfFirstSale"),
            "exemption_type": _exemption(root, ns),
            "revenue_range": _txt(root, ns, "revenueRange"),
            "related_persons": _related(root, ns),
        }
    except etree.XMLSyntaxError as e:
        log.warning(f"XML parse error: {e}")
        return None
    except Exception as e:
        log.error(f"Form D parse error: {e}")
        return None


def _ns(root) -> str:
    tag = root.tag
    return tag[1:tag.index("}")] if tag.startswith("{") else ""

def _p(ns): return f"{{{ns}}}" if ns else ""

def _txt(root, ns, tag) -> Optional[str]:
    el = root.find(f".//{_p(ns)}{tag}")
    return el.text.strip() if el is not None and el.text else None

def _flt(root, ns, tag) -> Optional[float]:
    v = _txt(root, ns, tag)
    try: return float(v.replace(",", "")) if v else None
    except ValueError: return None

def _int(root, ns, tag) -> Optional[int]:
    v = _txt(root, ns, tag)
    try: return int(v) if v else None
    except ValueError: return None

def _exemption(root, ns) -> Optional[str]:
    for ex in root.findall(f".//{_p(ns)}exemption"):
        if ex.text and "506" in ex.text:
            return ex.text.strip()
    return None

def _related(root, ns) -> list:
    persons = []
    for p in root.findall(f".//{_p(ns)}relatedPersonInfo"):
        first = _txt(p, ns, "relatedPersonFirstName")
        last = _txt(p, ns, "relatedPersonLastName")
        rel = _txt(p, ns, "relatedPersonRelationship")
        if first or last:
            persons.append({"name": f"{first or ''} {last or ''}".strip(), "relationship": rel})
    return persons
