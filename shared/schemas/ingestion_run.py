"""
Ingestion Run Audit Schema
==========================
Every worker run logs a record: what ran, when, how many records, any errors.
"""
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


class IngestionRun(SQLModel, table=True):
    __tablename__ = "ingestion_runs"

    id: str = Field(default_factory=_new_id, primary_key=True)
    service_name: str = Field(index=True, max_length=50)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    completed_at: Optional[datetime] = None
    status: str = Field(default="running", index=True, max_length=20)  # running | success | error | partial
    records_processed: int = Field(default=0)
    records_skipped: int = Field(default=0)
    errors: int = Field(default=0)
    error_messages: list = Field(default_factory=list, sa_column=Column(JSON))
    run_metadata: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
