# Alpha0Engine

> **Catalyst-driven micro-cap screening engine**
> Finds cheap public stocks with a dated binary catalyst, tiny float, and cash
> to reach the event — the setups that can re-rate 10x–200x — and surfaces them
> *before* the move. See `RESTRUCTURE.md` for the architecture rationale.

**CEO:** Driss | **CTO/Lead Dev:** AI-assisted build
**Stack:** Python · FastAPI · PostgreSQL · Railway · GitHub Actions

---

## How it works

```
[Public Sources]
SEC (8-K · Form 4 · 13F) · ClinicalTrials.gov · OpenFDA · Finnhub · yfinance
        |
  [Daily Pipeline]  scripts/run_daily_pipeline.py  (one process, sequential)
        |
  prices → SEC filings → catalysts (trials/FDA) → news
        |
  [Screener]  5 lenses per lane (binary catalyst · float mechanics ·
              smart money · earnings inflection · demand rider)
        |
  [Buckets]  NO TOUCH · WATCH · DEEP_DIVE · SETUP_READY
             (SETUP_READY only for live-validated lanes — see
              shared/scoring/calibration.py)
        |
  [Alerts]  Telegram memo with thesis, red flags, invalidation criteria
```

Lanes are code-as-config (`shared/lanes/`): a megatrend → bottleneck →
exposed-company thesis with lane-specific weights and risks. A lane's score
must prove itself on matured live alerts before it may emit `SETUP_READY`.

---

## Deploy topology

One Docker image (root `Dockerfile`), two Railway services:

| Service | Command | Schedule |
|---|---|---|
| `api` | image default (migrate + uvicorn) | Always on |
| `pipeline` | `python scripts/run_daily_pipeline.py` | Daily cron |

---

## Quick Start (Local)

```bash
git clone https://github.com/Driss-AI/Alpha0Engine.git
cd Alpha0Engine
cp .env.example .env
# Fill in your keys in .env
docker compose up                      # postgres + api
docker compose run --rm pipeline       # one full pipeline run
# API: http://localhost:8000
# Docs: http://localhost:8000/docs
# Dashboard: http://localhost:8000/
```

---

## Repo layout

```
services/          # pipeline workers + api (being consolidated — RESTRUCTURE.md §4)
shared/            # lanes, scoring, schemas, alert/memo services, clients
scripts/           # pipeline orchestrator, backtests, calibration
alembic/           # migrations
reports/           # backtest reports
```
