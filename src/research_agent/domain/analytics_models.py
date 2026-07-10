"""Analytics domain models."""

from datetime import datetime

from pydantic import BaseModel, Field


class AppSummary(BaseModel):
    """Human-facing summary for one app in the final report."""

    app_name: str = Field(min_length=1)
    category: str | None = None
    overall_status: str
    research_confidence: float = Field(ge=0, le=1)
    verification_confidence: float = Field(ge=0, le=1)
    key_findings: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class Analytics(BaseModel):
    """Aggregate run analytics."""

    total_apps: int = Field(ge=0)
    verified_count: int = Field(ge=0)
    partially_verified_count: int = Field(ge=0)
    unverified_count: int = Field(ge=0)
    contradicted_count: int = Field(ge=0)
    average_research_confidence: float = Field(ge=0, le=1)
    average_verification_confidence: float = Field(ge=0, le=1)
    category_breakdown: dict[str, int] = Field(default_factory=dict)
    top_flagged_apps: list[str] = Field(default_factory=list)
    app_summaries: list[AppSummary] = Field(default_factory=list)
    generated_at: datetime
