"""Universe hygiene — only real operating-company shares get scanned.

The exclusion examples below are all real tickers pulled from a production
screener log, where each one burned scoring time and price budget despite being
un-explodable by construction.
"""
from shared.universe import (
    EXCLUDED_ENTITY_TYPE,
    SCANNABLE_ENTITY_TYPE,
    classify_security,
    entity_type_for,
    is_scannable,
)


class TestExcludesDerivativeSecurities:
    def test_nasdaq_fifth_letter_warrants_units_rights(self):
        assert classify_security("XRPNW") == "warrant"   # Armada Acquisition II
        assert classify_security("DAAQW") == "warrant"   # Digital Asset Acq.
        assert classify_security("CCIIW") == "warrant"   # Cohen Circle II
        assert classify_security("QUMSU") == "unit"      # Quantumsphere Acq.
        assert classify_security("CCIIU") == "unit"      # Cohen Circle II
        assert classify_security("APMCU") == "unit"      # AmperCap Acq.
        assert classify_security("EGHAR") == "right"     # EGH Acquisition
        assert classify_security("QUMSR") == "right"     # Quantumsphere Acq.

    def test_nyse_style_suffixes(self):
        assert classify_security("PEW-WT") == "warrant"  # GrabAGun Digital
        assert classify_security("ABC.WS") == "warrant"
        assert classify_security("XYZ-UN") == "unit"
        assert classify_security("XYZ-RT") == "right"
        assert classify_security("XYZ-P") == "preferred"
        assert classify_security("XYZ-PR") == "preferred"

    def test_foreign_adrs_flagged_by_sec_title(self):
        assert classify_security("KXHCF", "Kioxia Holdings Corporation/ADR") == "foreign_adr"
        assert classify_security("ONWRF", "Onward Medical N.V./ADR") == "foreign_adr"
        assert classify_security("FKURF", "Fujikura Ltd/ADR") == "foreign_adr"
        assert classify_security("HRZRF", "Horizon Robotics, Inc./ADR") == "foreign_adr"

    def test_missing_or_absurd_ticker(self):
        assert classify_security(None) == "invalid_ticker"
        assert classify_security("") == "invalid_ticker"
        assert classify_security("WAYTOOLONGTICKER") == "invalid_ticker"


class TestKeepsRealMicroCaps:
    """The whole point is that genuine candidates survive the filter."""

    def test_biotech_candidates_are_scannable(self):
        # SPRB is the pattern the engine exists to catch; the rest are names
        # that have actually surfaced on the dashboard.
        for ticker in ("SPRB", "URGN", "HCWB", "GPCR", "RCUS", "MIRM", "CRVS"):
            assert is_scannable(ticker), f"{ticker} must stay in the universe"

    def test_ordinary_share_classes_survive(self):
        # A dotted share class is still common stock, not a derivative.
        assert classify_security("BRK.A") == "common"
        assert classify_security("GLIBK") == "common"   # Liberty tracking class

    def test_four_letter_tickers_ending_in_reserved_letters(self):
        # The 5th-letter convention applies only to 5-character symbols, so a
        # 4-letter biotech ending in R/U/W must not be swept up.
        for ticker in ("CLIR", "NUWE", "AEMD"):
            assert is_scannable(ticker), f"{ticker} must stay in the universe"

    def test_adr_marker_needs_the_sec_suffix(self):
        # "Radar" contains "adr" as a substring — matching that would be a bug.
        assert classify_security("RDAR", "Radar Therapeutics Inc") == "common"


class TestEntityTypeMapping:
    def test_scannable_maps_to_public(self):
        assert entity_type_for("SPRB", "Spruce Biosciences") == SCANNABLE_ENTITY_TYPE

    def test_junk_maps_to_excluded(self):
        assert entity_type_for("XRPNW", "Armada Acquisition Corp. II") == EXCLUDED_ENTITY_TYPE
        assert entity_type_for("KXHCF", "Kioxia Holdings Corporation/ADR") == EXCLUDED_ENTITY_TYPE
