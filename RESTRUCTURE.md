# Alpha0Engine Restructure Plan

**Goal restated (July 2026):** catch catalyst-driven micro-cap explosions — the
SPRB pattern: cheap public stocks (<$15) with a dated binary catalyst, tiny
float, and enough cash to reach the event, that can re-rate 10x–200x. Private
companies and IPO proximity are explicitly **not** the priority anymore.

Everything below is judged against that one goal. Three verdicts: **KILL**
(delete), **MERGE** (keep the logic, lose the service), **KEEP**.

---

## 1. The big structural problem: 19 services for a 1-person pipeline

The repo is shaped like a 10-team microservice platform: 19 services, 19
Dockerfiles, 19 Railway cron entries, Redis streams between them. But
`scripts/run_daily_pipeline.py` already runs everything **sequentially as
subprocesses in one process tree**. The microservice split buys nothing — no
independent scaling, no isolation benefit — and costs 19 deploy targets, 19
requirements.txt files, and a class of "worker orphaned from the orchestrator"
bugs (S11.2 fixed two of those).

**Change:** one repo package (`alpha0/`), **one Docker image**, **two Railway
services**:

| Railway service | What it runs |
|---|---|
| `api` | FastAPI gateway (unchanged behavior) |
| `pipeline` | `run_daily_pipeline.py` on cron — all ingest + scoring steps as in-process modules |

Kill all 19 per-service Dockerfiles. Kill Redis streams (each step writes to
Postgres; the next step reads Postgres — they run sequentially anyway). Redis
stays only if rate-limit state for the API needs it; otherwise drop the
dependency entirely.

This alone deletes ~17 Dockerfiles, most of docker-compose.yml, and the whole
"is the cron for X still wired?" failure class.

---

## 2. Service-by-service verdict

### KILL — built for the old private/IPO thesis, dead weight now

| Component | Lines | Why it goes |
|---|---:|---|
| `services/nlp-engine` (embedder, theme_detector, ipo_scorer) | ~650 | HDBSCAN theme clustering never fires (needs 20+ embeddings, skips), lanes are code-as-config now, and IPO-proximity scoring is the deprioritized goal. Drags in pgvector + numpy for nothing. |
| `services/ingest-github` + GH Archive | ~160 | Tracks OpenAI/HuggingFace org activity — a private-AI-company maturity signal. Zero relevance to micro-cap catalysts. |
| `services/ingest-patents` | ~190 | Patent grants almost never drive the SPRB pattern. The binary-catalyst lens weights it 0.70, which overstates it badly. Cut the source; drop `patent_grant` from CATALYST_WEIGHTS. |
| `services/ingest-edgar` (Form D) | ~345 | Form D = **private** placements. It was even marked `critical=True` and "primary catalyst source" in the pipeline — that's the old thesis talking. For public micro-caps it contributes nothing. |
| `fundamental-screener/private_proxy.py` | ~200 | Proxy-scoring private companies from Form D. Same story. |
| `services/brain` (Claude-based analyst) | ~1,750 | Duplicate analysis layer. Sprint 13 built the deterministic memo (`shared/services/memo.py`, explicitly "no LLM") that does the explainability job traceably. Brain adds API cost, a 1.5s-per-candidate serial crawl, and a second opportunities/narratives schema pair nobody consumes downstream. If LLM deep-dives are wanted later, make it an on-demand CLI (`python -m alpha0.deepdive TICKER`), not a nightly pipeline stage. |
| `services/entity-resolver` | ~280 | Existed to fuzzy-match private entities across Form D / patents / GitHub orgs. Public equities have a natural key: **ticker + CIK**. Replace with a ~50-line CIK↔ticker mapping in the ingest layer. |
| API routers: `ipo.py`, `themes.py`, `signals.py`, `brain.py`, `fundamentals.py` | ~600 | Serve the killed subsystems / raw internals no client needs. |
| Schemas: `embeddings`, `themes`, `brain_opportunity`, `brain_narrative` | — | Orphaned by the above. One down-migration drops the tables. |

**Killed outright: ~4,200 lines of Python + 8 services + pgvector + the Anthropic dependency in the nightly path.**

### MERGE — right logic, wrong shape

| Components | Into | Why |
|---|---|---|
| `fundamental-screener` + `risk-filter` + `screener-1000x` | one `alpha0/screener/` module | Three services that run back-to-back on the same entities and pass results through DB tables. Red flags already moved to `shared/scoring/red_flags.py`; finish the move. One scoring pass: fundamentals → risk flags → lenses → composite → bucket. |
| `ingest-trials` + `ingest-fda` | one `alpha0/catalysts/` module | Both exist to answer one question: **what dated events are coming?** Merge them and have them write `catalyst_event` rows as the primary output (see §3). |
| `ingest-8k` + `ingest-form4` + `ingest-13f` | one `alpha0/sec/` module | Three SEC pollers with three copies of EDGAR client boilerplate. One client, three parsers. |
| 20 API routers | ~7 | `health`, `screener` (screens+deep_dive+deltas), `catalysts`, `alerts`, `watchlist`, `prices`, `ops` (pipeline_health+data_freshness+metrics+dashboard). |

### KEEP — this is the actual product

- `ingest-prices` — universe discovery + OHLCV + market cap. The backbone.
- `ingest-news` (Finnhub) — catalyst confirmation + hype detection input.
- `screener-1000x` lens logic — **`lens_binary_catalyst.py` is literally the
  SPRB pattern** and `lens_float_mechanics.py` is the squeeze-amplifier math.
  These two are the crown jewels. `lens_smart_money`, `lens_earnings_inflection`,
  `lens_demand_rider` keep as secondary lenses.
- `shared/scoring/*` — axes, buckets, red flags, thesis, memo, and especially
  the **calibration state machine**. Do not touch the live_validated gating.
- `alert-engine` (Telegram) — the delivery mechanism. Keep.
- `scripts/` backtest + calibration tooling. Keep.
- `ingest-hyperscaler-capex` — keep **only while the L1 AI-infra lane stays on**
  (it's the validated lane; it pays the bills while L2 gets fixed). Optional step.

---

## 3. What's missing for the SPRB goal (build after the cut)

1. **Catalyst calendar as the spine.** `catalyst_event` schema exists but events
   are a side-effect today. Invert it: the screener should iterate over
   *upcoming dated events* (PDUFA dates, trial readout windows, AdCom dates) and
   score the companies attached to them — not iterate over all entities hoping a
   catalyst signal is lying around.
2. **Real float + short interest ingestion.** `lens_float_mechanics` currently
   reconstructs float from EDGAR shares-outstanding. Add FINRA bi-monthly short
   interest + a float source. This is the highest-value new data for the goal.
3. **Event-conditioned scoring for L2.** The backtest already proved the linear
   composite fails on binary names (corr +0.07). Score = payoff shape
   (cap-vs-market-if-win × catalyst proximity × cash runway × float), not a
   weighted average of trend axes.
4. **Retrospective catch-rate suite.** Reconstruct what was publicly knowable
   30/60/90 days before SPRB-class moves (10–20 cases) and assert the
   engine surfaces them at DEEP_DIVE+. This becomes the regression test for the
   whole product.

---

## 4. Target repo shape

```
alpha0/
  ingest/
    prices.py        # universe + OHLCV + mcap (was ingest-prices)
    sec.py           # 8-K, Form 4, 13F (one EDGAR client)
    catalysts.py     # trials + FDA → catalyst_event rows
    news.py          # Finnhub
    short_interest.py# NEW — FINRA SI + float
    capex.py         # optional, L1 only
  screener/
    lenses/          # binary_catalyst, float_mechanics, smart_money, ...
    composite.py, red_flags.py, buckets.py, calibration.py, thesis.py, memo.py
  alerts/            # telegram + memo rendering
  api/               # FastAPI, ~7 routers
  pipeline.py        # the orchestrator, importing modules (no subprocesses)
scripts/             # backtest, calibration, catch-rate suite
Dockerfile           # ONE
docker-compose.yml   # postgres + api + pipeline (+ redis only if kept)
```

Pipeline: `prices → sec → catalysts → news → short_interest → screener → alerts`.
Seven steps instead of twenty.

---

## 5. Order of operations

1. **Cut first, refactor second.** Delete the KILL list + their pipeline steps,
   routers, schemas, Dockerfiles. Nothing downstream breaks that isn't already
   dead. (~1 day, mostly deletions — the win is immediate.)
2. Collapse deploy to one image / two Railway services.
3. Merge the screener trio and the SEC trio.
4. Build the catalyst calendar inversion + short-interest ingest.
5. Build the retrospective catch-rate suite; wire it into CI next to the
   existing backtest.

Net effect: ~20k → ~12k lines, 19 services → 2 deploy targets, 20 routers → 7,
and every remaining line answers one question: *is there a cheap stock with a
dated catalyst, a tiny float, and cash to get there — and did we surface it
before the move?*
