"""
Entity Master Schema
====================
Canonical company record. All signals join on entity_id.
Stable UUID forever — never changes.
"""
from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


class EntityBase(SQLModel):
    name: str = Field(index=True)
    domain: Optional[str] = Field(default=None, index=True)
    cik: Optional[str] = Field(default=None, index=True)
    ein: Optional[str] = Field(default=None)
    lei: Optional[str] = Field(default=None)
    crunchbase_id: Optional[str] = Field(default=None)
    pitchbook_id: Optional[str] = Field(default=None)
    github_org: Optional[str] = Field(default=None, index=True)
    ticker: Optional[str] = Field(default=None, index=True)
    entity_type: str = Field(default="private")
    sector: Optional[str] = Field(default=None)
    subsector: Optional[str] = Field(default=None)
    stage: Optional[str] = Field(default=None)
    hq_country: Optional[str] = Field(default=None)
    hq_city: Optional[str] = Field(default=None)
    founded_year: Optional[int] = Field(default=None)
    description: Optional[str] = Field(default=None)
    resolution_confidence: float = Field(default=1.0)


class Entity(EntityBase, table=True):
    __tablename__ = "entities"
    id: str = Field(default_factory=_new_id, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class EntityCreate(EntityBase):
    pass


class EntityRead(EntityBase):
    id: str
    created_at: datetime
    updated_at: datetime


class EntityUpdate(SQLModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    cik: Optional[str] = None
    ticker: Optional[str] = None
    entity_type: Optional[str] = None
    sector: Optional[str] = None
    stage: Optional[str] = None
    github_org: Optional[str] = None
    description: Optional[str] = None
    hq_country: Optional[str] = None
    hq_city: Optional[str] = None
