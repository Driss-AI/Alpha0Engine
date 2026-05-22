"""
Theme Schema
============
Megatrend themes detected by NLP clustering.
Each theme represents an emerging technology/market cluster.
velocity_score: 0.0 (dormant) to 1.0 (explosive growth)
"""
from typing import Optional, List
from datetime import datetime
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


class ThemeBase(SQLModel):
    name: str = Field(index=True)
    description: Optional[str] = None
    keywords: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    velocity_score: float = Field(default=0.0)      # 0.0-1.0 growth rate
    entity_count: int = Field(default=0)
    signal_count: int = Field(default=0)
    avg_similarity: float = Field(default=0.0)
    status: str = Field(default="emerging")          # emerging|active|cooling|dead


class Theme(ThemeBase, table=True):
    __tablename__ = "themes"
    id: str = Field(default_factory=_new_id, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ThemeCreate(ThemeBase):
    pass


class ThemeRead(ThemeBase):
    id: str
    created_at: datetime
    updated_at: datetime


class ThemeEntity(SQLModel, table=True):
    """Maps entities to themes with similarity scores."""
    __tablename__ = "theme_entities"
    id: str = Field(default_factory=_new_id, primary_key=True)
    theme_id: str = Field(index=True)
    entity_id: str = Field(index=True)
    similarity_score: float = Field(default=0.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
