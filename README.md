# Alpha0Engine

> **Dual-pipeline asymmetric return screening engine**
> Identifies 10x–1000x return opportunities from late-stage private market through early public lifecycle.

**CEO:** Driss | **CTO/Lead Dev:** AI-assisted build
**Stack:** Python · FastAPI · PostgreSQL · Redis · Cloudflare R2 · Railway · GitHub Actions

---

## Build Status

| Module | Status | Description |
|--------|--------|-------------|
| M1: Data Ingestion | 🟡 Live | EDGAR, USPTO, GitHub Archive, Entity Resolver |
| M2: Signal Detection | ⚪ Next | NLP megatrend detection, IPO proximity signals |
| M3: Fundamental Screening | ⚪ Planned | Moat metrics, proxy valuation |
| M4: Risk Filtering | ⚪ Planned | Hype detection, illiquidity thresholds |
| M5: Mobile App | ⚪ Planned | iOS + Android via React Native |

---

## Services

| Service | Purpose | Schedule |
|---------|---------|----------|
| `api` | FastAPI gateway — all client endpoints | Always on |
| `ingest-edgar` | SEC Form D scraper | Daily 06:00 UTC |
| `ingest-patents` | USPTO PatentsView connector | Weekly Sun 02:00 UTC |
| `ingest-github` | GitHub Archive consumer | Hourly |
| `entity-resolver` | Cross-source entity deduplication | Daily batch + stream |

---

## Architecture

```
[Public Sources]                    [Private Sources]
USPTO · EDGAR · GH Archive          PitchBook · Caplight · Forge
        |                                   |
  [Ingest Workers]               [Ingest Workers]
        |                                   |
        +--------[Redis Streams]-----------+
                        |
               [Entity Resolver]
           (probabilistic matching)
                        |
           [PostgreSQL Core DB]
       entities | signals | scores
                        |
           [FastAPI Gateway :8000]
                        |
              [Mobile App] (M5)
```

---

## Quick Start (Local)

```bash
git clone https://github.com/Driss-AI/Alpha0Engine.git
cd Alpha0Engine
cp .env.example .env
# Fill in your keys in .env
docker-compose up
# API: http://localhost:8000
# Docs: http://localhost:8000/docs
```

---

## Railway Deployment

Railway project: **Alpha0Engine** (`5aac4847-b098-41b9-ae51-151ba96ff2d8`)

For each service in Railway dashboard:
1. New Service → GitHub Repo → `Alpha0Engine`
2. Settings → Build → Dockerfile Path → e.g. `Dockerfile.api`
3. Add env vars from `.env.example`

Push to `main` → CI runs → Railway auto-deploys.
