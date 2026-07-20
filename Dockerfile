FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*

# One image for both Railway services:
#   api      -> CMD alembic upgrade head && uvicorn (default)
#   pipeline -> override command: python scripts/run_daily_pipeline.py
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY scripts/ ./scripts/
COPY services/ ./services/

ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn services.api.main:app --host 0.0.0.0 --port 8000"]
