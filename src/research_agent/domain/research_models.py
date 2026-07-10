"""Research result models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from research_agent.domain.enums import EvidenceType, ResearchStatus


class Evidence(BaseModel):
    """A short evidence snippet gathered from a source."""

    source_url: HttpUrl
    source_type: EvidenceType = EvidenceType.OTHER
    excerpt: str = Field(min_length=1, max_length=1000)
    relevance_score: float = Field(ge=0, le=1)
    retrieved_at: datetime


class ResearchResult(BaseModel):
    """Research agent output for one app."""

    app_name: str = Field(min_length=1)
    status: ResearchStatus
    summary: str
    category: str | None = None
    documentation_urls: list[HttpUrl] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence_score: float = Field(ge=0, le=1)
    researched_at: datetime
    raw_agent_metadata: dict[str, Any] | None = None
