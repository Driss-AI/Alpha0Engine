"""
Load test for the Alpha0Engine API (Sprint 5.7).

Simulates realistic read traffic — a viewer browsing the dashboard, screener,
brain picks, and entity/signal detail pages. Write endpoints are excluded so a
load run never mutates production data.

Run against staging (NOT prod) with 100 concurrent users:

    pip install locust
    export API_KEY=...            # a viewer key
    locust -f tests/load/locustfile.py \
        --host https://alpha0engine-staging.up.railway.app \
        --users 100 --spawn-rate 10 --run-time 5m --headless

Pass/fail target (Sprint 5 QA gate): p99 < 500ms at 100 concurrent users.
Locust prints per-endpoint p50/p95/p99 and failure rate at the end.
"""
import os
import random

from locust import HttpUser, task, between, events

API_KEY = os.environ.get("API_KEY", "")

# A small pool of tickers for detail-page requests. Override with TICKERS env
# (comma-separated) to match the data actually present in the target DB.
TICKERS = [t.strip().upper() for t in os.environ.get(
    "TICKERS", "AAPL,TSLA,MRNA,NVDA,AMD,PLTR,SOFI,RIOT"
).split(",") if t.strip()]


class ViewerUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        self.client.headers.update({"X-API-Key": API_KEY})

    # ── high-frequency list views ────────────────────────────────
    @task(10)
    def screener(self):
        self.client.get("/api/v1/1000x?limit=50", name="/1000x")

    @task(6)
    def brain_picks(self):
        self.client.get("/api/v1/brain/picks?limit=25", name="/brain/picks")

    @task(5)
    def entities(self):
        self.client.get("/api/v1/entities?limit=50", name="/entities")

    @task(5)
    def signals(self):
        self.client.get("/api/v1/signals?limit=50", name="/signals")

    @task(4)
    def deltas(self):
        self.client.get("/api/v1/1000x/deltas", name="/1000x/deltas")

    @task(3)
    def catalysts(self):
        self.client.get("/api/v1/catalysts/calendar", name="/catalysts/calendar")

    @task(3)
    def screener_summary(self):
        self.client.get("/api/v1/1000x/summary", name="/1000x/summary")

    @task(2)
    def watchlist(self):
        self.client.get("/api/v1/watchlist", name="/watchlist")

    # ── detail pages ─────────────────────────────────────────────
    @task(4)
    def ticker_detail(self):
        ticker = random.choice(TICKERS)
        self.client.get(f"/api/v1/1000x/{ticker}", name="/1000x/{ticker}")

    @task(2)
    def brain_narrative(self):
        ticker = random.choice(TICKERS)
        self.client.get(f"/api/v1/brain/{ticker}/narrative", name="/brain/{ticker}/narrative")

    # ── ops endpoints ────────────────────────────────────────────
    @task(1)
    def health(self):
        self.client.get("/health", name="/health")

    @task(1)
    def metrics(self):
        self.client.get("/api/v1/metrics", name="/metrics")


@events.test_start.add_listener
def _warn_no_key(environment, **_):
    if not API_KEY:
        print("WARNING: API_KEY not set — every request will likely 401/403.")


@events.quitting.add_listener
def _enforce_p99(environment, **_):
    """Fail the run (non-zero exit) if the p99 SLA is breached."""
    p99 = environment.stats.total.get_response_time_percentile(0.99)
    fail_ratio = environment.stats.total.fail_ratio
    if p99 is not None and p99 > 500:
        print(f"SLA BREACH: p99 {p99:.0f}ms > 500ms target")
        environment.process_exit_code = 1
    if fail_ratio > 0.01:
        print(f"SLA BREACH: failure ratio {fail_ratio:.2%} > 1%")
        environment.process_exit_code = 1
