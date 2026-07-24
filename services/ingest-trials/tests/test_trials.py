"""
Tests — Clinical Trial Ingestion
===================================
Tests for CT.gov API parsing, trial-to-entity matching,
and catalyst proximity computation.
"""
import sys
import os
import pytest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trial_matcher import _normalize, _match_score, match_sponsor_to_entities, build_entity_index, match_sponsor_indexed
from ct_client import _parse_ct_date, _extract_study


# ═══════════════════════════════════════════════════════════
# Name Normalization
# ═══════════════════════════════════════════════════════════
class TestNormalization:
    def test_strip_inc(self):
        assert _normalize("Supernus Pharmaceuticals, Inc.") == "supernus"

    def test_strip_corp(self):
        assert _normalize("Acacia Research Corporation") == "acacia research"

    def test_strip_ltd(self):
        assert _normalize("AstraZeneca Ltd") == "astrazeneca"

    def test_lowercase(self):
        assert _normalize("NVIDIA") == "nvidia"

    def test_empty(self):
        assert _normalize("") == ""

    def test_multiple_suffixes(self):
        result = _normalize("BioGen Therapeutics Inc.")
        assert "biogen" in result
        assert "inc" not in result


# ═══════════════════════════════════════════════════════════
# Match Scoring
# ═══════════════════════════════════════════════════════════
class TestMatchScore:
    def test_exact_match(self):
        score = _match_score("Supernus Pharmaceuticals", "Supernus Pharmaceuticals Inc.")
        assert score >= 0.9

    def test_partial_match(self):
        score = _match_score("Acacia Research", "Acacia Research Corporation")
        assert score >= 0.7

    def test_no_match(self):
        score = _match_score("Apple Inc", "Microsoft Corporation")
        assert score < 0.3

    def test_empty(self):
        score = _match_score("", "Test Corp")
        assert score == 0.0

    def test_similar_biotech(self):
        score = _match_score("Moderna, Inc.", "Moderna")
        assert score >= 0.9


# ═══════════════════════════════════════════════════════════
# Entity Matching
# ═══════════════════════════════════════════════════════════
class TestEntityMatching:
    def setup_method(self):
        self.entities = [
            {"id": "1", "name": "Supernus Pharmaceuticals", "ticker": "SUPN"},
            {"id": "2", "name": "Moderna", "ticker": "MRNA"},
            {"id": "3", "name": "Pfizer", "ticker": "PFE"},
            {"id": "4", "name": "Apple", "ticker": "AAPL"},
            {"id": "5", "name": "Acacia Research", "ticker": "ACTG"},
        ]

    def test_match_with_suffix(self):
        result = match_sponsor_to_entities("Supernus Pharmaceuticals, Inc.", self.entities)
        assert result is not None
        assert result["ticker"] == "SUPN"

    def test_match_exact(self):
        result = match_sponsor_to_entities("Moderna", self.entities)
        assert result is not None
        assert result["ticker"] == "MRNA"

    def test_match_pfizer(self):
        result = match_sponsor_to_entities("Pfizer Inc.", self.entities)
        assert result is not None
        assert result["ticker"] == "PFE"

    def test_no_match_threshold(self):
        result = match_sponsor_to_entities("RandomUnknownCompany LLC", self.entities)
        assert result is None

    def test_indexed_match(self):
        index = build_entity_index(self.entities)
        result = match_sponsor_indexed("Moderna, Inc.", index, self.entities)
        assert result is not None
        assert result["ticker"] == "MRNA"


# ═══════════════════════════════════════════════════════════
# Date Parsing
# ═══════════════════════════════════════════════════════════
class TestDateParsing:
    def test_iso_date(self):
        dt = _parse_ct_date("2026-06-15")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 6

    def test_month_only(self):
        dt = _parse_ct_date("2026-06")
        assert dt is not None
        assert dt.year == 2026

    def test_none(self):
        assert _parse_ct_date(None) is None

    def test_empty(self):
        assert _parse_ct_date("") is None


# ═══════════════════════════════════════════════════════════
# Study Extraction
# ═══════════════════════════════════════════════════════════
class TestStudyExtraction:
    def test_extract_basic(self):
        """Test extraction from a minimal CT.gov v2 response."""
        study = {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT12345678",
                    "briefTitle": "Study of Drug X in Cancer",
                },
                "statusModule": {
                    "overallStatus": "RECRUITING",
                    "startDateStruct": {"date": "2025-01-15"},
                    "primaryCompletionDateStruct": {"date": "2026-08-01"},
                },
                "sponsorCollaboratorsModule": {
                    "leadSponsor": {
                        "name": "TestPharma Inc.",
                        "class": "INDUSTRY",
                    },
                },
                "designModule": {
                    "phases": ["PHASE3"],
                },
                "conditionsModule": {
                    "conditions": ["Non-Small Cell Lung Cancer"],
                },
                "armsInterventionsModule": {
                    "interventions": [
                        {"name": "Drug X", "type": "DRUG", "description": "Test drug"},
                    ],
                },
            },
        }
        result = _extract_study(study)
        assert result["nct_id"] == "NCT12345678"
        assert result["phase"] == "PHASE3"
        assert result["status"] == "RECRUITING"
        assert result["lead_sponsor"] == "TestPharma Inc."
        assert result["sponsor_class"] == "INDUSTRY"
        assert result["primary_completion_date"] == "2026-08-01"
        assert result["primary_completion_dt"] is not None
        assert result["primary_completion_dt"].year == 2026
        assert len(result["conditions"]) == 1
        assert len(result["interventions"]) == 1

    def test_extract_empty(self):
        """Empty study should not crash."""
        result = _extract_study({})
        assert result["nct_id"] == ""
        assert result["phase"] == ""


# ═══════════════════════════════════════════════════════════
# Catalyst Proximity (from main.py)
# ═══════════════════════════════════════════════════════════
class TestCatalystProximity:
    def test_future_date(self):
        from main import _compute_catalyst_proximity
        trial = {
            "primary_completion_dt": datetime.utcnow() + timedelta(days=45),
        }
        days = _compute_catalyst_proximity(trial)
        assert days is not None
        assert 44 <= days <= 46

    def test_past_date(self):
        from main import _compute_catalyst_proximity
        trial = {
            "primary_completion_dt": datetime.utcnow() - timedelta(days=10),
        }
        days = _compute_catalyst_proximity(trial)
        assert days is not None
        assert days < 0

    def test_no_date(self):
        from main import _compute_catalyst_proximity
        trial = {}
        days = _compute_catalyst_proximity(trial)
        assert days is None

    def test_signal_value_phase3_near(self):
        from main import _compute_signal_value
        trial = {"phase": "PHASE3", "status": "ACTIVE_NOT_RECRUITING"}
        value = _compute_signal_value(trial, proximity_days=25)
        assert value >= 0.9  # Phase 3 + near + active

    def test_signal_value_phase2_far(self):
        from main import _compute_signal_value
        trial = {"phase": "PHASE2", "status": "RECRUITING"}
        value = _compute_signal_value(trial, proximity_days=300)
        assert 0.4 <= value <= 0.6

    def test_catalyst_type_phase3(self):
        from main import _classify_catalyst_type
        assert _classify_catalyst_type({"phase": "PHASE3", "status": "RECRUITING"}) == "fda_pdufa"
        assert _classify_catalyst_type({"phase": "PHASE3", "status": "COMPLETED"}) == "clinical_trial_data"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ═══════════════════════════════════════════════════════════
# v2 param building — the filter.phase 400 regression
# ═══════════════════════════════════════════════════════════
from ct_client import _build_params, _phase_codes, _phase_matches, _get_with_retry  # noqa: E402


class TestV2Params:
    def test_never_emits_invalid_filter_phase(self):
        p = _build_params(sponsor=None, condition=None, intervention=None,
                          phases=["PHASE2", "PHASE3"], statuses=["RECRUITING"], page_size=100)
        assert "filter.phase" not in p                      # the bug that 400'd
        assert p["aggFilters"] == "phase:2 3"               # v2-correct
        assert p["filter.overallStatus"] == "RECRUITING"

    def test_phase_codes_handles_combined(self):
        assert _phase_codes(["PHASE2/PHASE3"]) == ["2", "3"]
        assert _phase_codes(["PHASE3"]) == ["3"]

    def test_sponsor_query_param(self):
        p = _build_params(sponsor="Spruce Bio", condition=None, intervention=None,
                          phases=[], statuses=[], page_size=50)
        assert p["query.spons"] == "Spruce Bio"
        assert "aggFilters" not in p

    def test_client_side_phase_guard(self):
        assert _phase_matches("PHASE3", ["PHASE2", "PHASE3"]) is True
        assert _phase_matches("PHASE1", ["PHASE2", "PHASE3"]) is False
        assert _phase_matches("", ["PHASE3"]) is False


class TestRetry:
    def test_429_backs_off_then_succeeds(self, monkeypatch):
        import asyncio
        import ct_client

        sleeps = []

        async def fake_sleep(s):
            sleeps.append(s)

        class Resp:
            def __init__(self, code):
                self.status_code = code
                self.headers = {}

        class FakeClient:
            def __init__(self):
                self.n = 0

            async def get(self, url, params=None):
                self.n += 1
                return Resp(429) if self.n < 3 else Resp(200)

        monkeypatch.setattr(ct_client.asyncio, "sleep", fake_sleep)
        resp = asyncio.run(
            _get_with_retry(FakeClient(), {})
        )
        assert resp.status_code == 200
        assert len(sleeps) == 2  # backed off twice before the 200


# ═══════════════════════════════════════════════════════════
# Signal upsert idempotency — the UniqueViolation regression
# ═══════════════════════════════════════════════════════════
import asyncio  # noqa: E402
from datetime import datetime as _dt  # noqa: E402


class TestTrialSignalUpsert:
    def test_same_nct_two_entities_no_duplicate(self):
        """Two entities matching the same trial must yield ONE signal, no crash."""
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlmodel import SQLModel, select
        from sqlmodel.ext.asyncio.session import AsyncSession
        from shared.schemas.signals import Signal
        import main as trials_main

        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)
            async with AsyncSession(engine) as session:
                common = dict(
                    nct_id="NCT06188702", signal_value=0.8, raw_data={"x": 1},
                    signal_date=_dt(2027, 5, 1), notes="phase 3",
                )
                o1 = await trials_main._upsert_trial_signal(session, entity_id="ENT_A", **common)
                o2 = await trials_main._upsert_trial_signal(session, entity_id="ENT_B", **common)
                await session.commit()  # would raise UniqueViolation under the old code
                rows = (await session.exec(
                    select(Signal).where(Signal.source_id == "NCT06188702")
                )).all()
                return o1, o2, rows

        o1, o2, rows = asyncio.run(scenario())
        assert o1 == "created"
        assert o2 == "updated"              # second match updates, not inserts
        assert len(rows) == 1               # exactly one signal survives
        assert rows[0].entity_id == "ENT_B"  # re-pointed to the latest match


class TestPersistClinicalTrial:
    def test_dict_interventions_persist_and_emit_catalyst(self):
        """Interventions arrive as dicts; persist must not crash and must emit a catalyst."""
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlmodel import SQLModel, select
        from sqlmodel.ext.asyncio.session import AsyncSession
        from shared.schemas.clinical_trial import ClinicalTrial
        from shared.schemas.catalyst_event import CatalystEvent
        import main as trials_main

        trial = {
            "nct_id": "NCT01920711",
            "title": "A Phase 3 study of DrugX",
            "phase": "PHASE3",
            "status": "ACTIVE_NOT_RECRUITING",
            "lead_sponsor": "Spruce Bio",
            "conditions": ["Solid Tumors", "Melanoma"],
            "interventions": [
                {"name": "DrugX", "type": "DRUG", "description": "the asset"},
                {"name": "Placebo", "type": "OTHER", "description": ""},
            ],
            "primary_completion_dt": _dt(2027, 3, 1),
            "enrollment": 120,
        }

        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)
            async with AsyncSession(engine) as session:
                await trials_main._persist_clinical_trial(
                    session, trial=trial, entity_id="ENT_A",
                    ticker="SPRB", company="Spruce Bio", proximity_days=220,
                )
                await session.commit()  # crashed here under the old str-join bug
                ct = (await session.exec(select(ClinicalTrial))).all()
                cats = (await session.exec(select(CatalystEvent))).all()
                return ct, cats

        ct, cats = asyncio.run(scenario())
        assert len(ct) == 1
        assert ct[0].intervention == "DrugX, Placebo"   # names joined, not dicts
        assert len(cats) == 1                            # catalyst emitted (calendar date)
        assert cats[0].ticker == "SPRB"


class TestMatchPrecision:
    def test_short_ticker_name_does_not_false_match(self):
        # Xos, Inc. (EV truck maker) must NOT match biotech sponsors that merely
        # contain the letters "xos".
        assert _match_score("Exosome Diagnostics, Inc.", "Xos, Inc.") < 0.6
        assert _match_score("Exoxemis, Inc.", "Xos, Inc.") < 0.6
        assert _match_score("BioXcel Therapeutics", "Xos, Inc.") < 0.6

    def test_real_biotech_still_matches(self):
        assert _match_score("UroGen Pharmaceuticals, Inc.", "UroGen Pharmaceuticals") >= 0.9
        assert _match_score("Candel Therapeutics, Inc.", "Candel Therapeutics, Inc.") == 1.0
        assert _match_score("Beam Therapeutics Inc.", "Beam Therapeutics") >= 0.9

    def test_word_boundary_containment(self):
        # extra corporate words still match at word boundaries
        assert _match_score("Arcturus Therapeutics Holdings Inc.", "Arcturus Therapeutics") >= 0.9
        # a shared distinctive word matches; unrelated short fragments do not
        assert _match_score("Structure Therapeutics Inc.", "Structure Therapeutics") >= 0.9

    def test_exact_short_name_still_allowed(self):
        # identical short names are fine (exact match path)
        assert _match_score("Xos, Inc.", "Xos, Inc.") == 1.0


class TestOrphanPrune:
    def test_prunes_false_match_keeps_current(self):
        """A stale/false clinical_trial signal (NCT not in this run) is deleted;
        current ones survive. Guard blocks pruning when too few current matches."""
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlmodel import SQLModel, select
        from sqlmodel.ext.asyncio.session import AsyncSession
        from shared.schemas.signals import Signal
        import main as trials_main

        async def scenario(keep, floor_ok):
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)
            async with AsyncSession(engine) as session:
                # 60 legit current + 1 orphan false match (XOS)
                for i in range(60):
                    session.add(Signal(entity_id=f"E{i}", signal_type="clinical_trial",
                                       signal_date=_dt(2027, 1, 1), value=0.8,
                                       source="clinicaltrials_gov",
                                       source_id=f"NCT{i:06d}", notes=""))
                session.add(Signal(entity_id="XOS", signal_type="clinical_trial",
                                   signal_date=_dt(2027, 1, 1), value=0.8,
                                   source="clinicaltrials_gov",
                                   source_id="NCT999999", notes="false match"))
                await session.commit()
                removed = await trials_main._prune_orphan_trial_signals(session, keep)
                rows = (await session.exec(select(Signal))).all()
                return removed, {r.source_id for r in rows}

        keep = {f"NCT{i:06d}" for i in range(60)}  # 60 current, XOS orphan excluded
        removed, remaining = asyncio.run(scenario(keep, True))
        assert removed == 1
        assert "NCT999999" not in remaining          # XOS orphan gone
        assert "NCT000000" in remaining               # legit kept

        # Guard: too few current matches → prune nothing (avoids wiping on bad fetch)
        removed2, remaining2 = asyncio.run(scenario({"NCT000001"}, False))
        assert removed2 == 0
        assert "NCT999999" in remaining2


class TestOrphanCatalystPrune:
    def test_prunes_false_calendar_catalyst_keeps_pinned_and_current(self):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlmodel import SQLModel, select
        from sqlmodel.ext.asyncio.session import AsyncSession
        from shared.schemas.catalyst_event import CatalystEvent
        import main as trials_main

        async def scenario():
            engine = create_async_engine("sqlite+aiosqlite://")
            async with engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)
            async with AsyncSession(engine) as session:
                # 60 current trial catalysts (keep)
                for i in range(60):
                    session.add(CatalystEvent(
                        ticker=f"BIO{i}", catalyst_type="trial_readout",
                        title="readout", user_pinned=False,
                        details={"bottleneck": "clinical_trial", "nct_id": f"NCT{i:06d}"}))
                # false match — XOS trial catalyst (orphan, NCT not current)
                session.add(CatalystEvent(
                    ticker="XOS", catalyst_type="trial_readout", title="fake FDA",
                    user_pinned=False,
                    details={"bottleneck": "clinical_trial", "nct_id": "NCT999999"}))
                # a user-pinned event with the same shape must SURVIVE
                session.add(CatalystEvent(
                    ticker="MINE", catalyst_type="trial_readout", title="my note",
                    user_pinned=True,
                    details={"bottleneck": "clinical_trial", "nct_id": "NCT999998"}))
                # an FDA-sourced catalyst must be untouched
                session.add(CatalystEvent(
                    ticker="OTHR", catalyst_type="fda", title="pdufa",
                    user_pinned=False, details={"bottleneck": "fda_decision"}))
                await session.commit()
                keep = {f"NCT{i:06d}" for i in range(60)}
                removed = await trials_main._prune_orphan_trial_catalysts(session, keep)
                rows = (await session.exec(select(CatalystEvent))).all()
                return removed, {r.ticker for r in rows}

        removed, tickers = asyncio.run(scenario())
        assert removed == 1
        assert "XOS" not in tickers        # false calendar catalyst gone
        assert "MINE" in tickers           # user-pinned survives
        assert "OTHR" in tickers           # non-trial catalyst untouched
        assert "BIO0" in tickers           # current trial catalyst kept


class TestSectorGate:
    def test_non_medical_sectors_rejected(self):
        from main import _sector_allows_trial
        assert _sector_allows_trial("Healthcare") is True
        assert _sector_allows_trial("Biotechnology") is True
        assert _sector_allows_trial("Pharmaceuticals") is True
        assert _sector_allows_trial(None) is True            # unknown allowed
        assert _sector_allows_trial("") is True
        assert _sector_allows_trial("Basic Materials") is False   # ATI Inc (metals)
        assert _sector_allows_trial("Consumer Cyclical") is False  # XOS (autos)
        assert _sector_allows_trial("Financial Services") is False
