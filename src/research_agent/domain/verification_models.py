"""Verification result models."""

from datetime import datetime

from pydantic import BaseModel, Field

from research_agent.domain.enums import VerificationStatus
from research_agent.domain.research_models import Evidence


class VerificationResult(BaseModel):
    """Verification agent output for one research result."""

    app_name: str = Field(min_length=1)
    research_result_ref: str = Field(min_length=1)
    verification_status: VerificationStatus
    confidence_score: float = Field(ge=0, le=1)
    discrepancies: list[str] = Field(default_factory=list)
    supporting_evidence: list[Evidence] = Field(default_factory=list)
    verified_at: datetime
