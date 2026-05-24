"""
Pipeline Health Schema
=======================
Tracks operational status of every data pipeline.
Each pipeline writes a heartbeat after each run cycle.
The dashboard reads this to show green/yellow/red status per pipeline.

Stale = pipeline hasn't reported in longer than its expected interval.
"""
from typing import Optional, Dict, Any
from datetime import datetime
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


class PipelineHealthBase(SQLModel):
    pipeline_name: str = Field(index=True, unique=True)  # e.g. "ingest-prices"
    status: str = Field(default="unknown")  # ok / warning / error / stale
    last_run_at: Optional[datetime] = Field(default=None)
    last_success_at: Optional[datetime] = Field(default=None)
    last_error_at: Optional[datetime] = Field(default=None)
    last_error_message: Optional[str] = Field(default=None)
    records_processed: int = Field(default=0)
    run_duration_seconds: Optional[float] = Field(default=None)
    expected_interval_hours: float = Field(default=24.0)  # How often it should run
    run_count: int = Field(default=0)
    error_count: int = Field(default=0)
    metadata_json: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class PipelineHealth(PipelineHealthBase, table=True):
    __tablename__ = "pipeline_health"
    id: str = Field(default_factory=_new_id, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PipelineHealthRead(PipelineHealthBase):
    id: str
    created_at: datetime
    updated_at: datetime
