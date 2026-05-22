"""
Embedding Schema
================
Vector embeddings for semantic search and theme clustering.
Uses pgvector for efficient similarity search.
"""
from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())


class Embedding(SQLModel, table=True):
    __tablename__ = "embeddings"
    id: str = Field(default_factory=_new_id, primary_key=True)
    entity_id: str = Field(index=True)
    text: str                                  # original text that was embedded
    source: str = Field(index=True)           # patent_abstract|form_d_desc|paper_abstract|13f_filing
    source_id: Optional[str] = None           # link back to signal/patent
    # vector stored separately via raw SQL (pgvector doesn't integrate with SQLModel directly)
    embedding_model: str = Field(default="all-MiniLM-L6-v2")
    dimensions: int = Field(default=384)
    created_at: datetime = Field(default_factory=datetime.utcnow)
