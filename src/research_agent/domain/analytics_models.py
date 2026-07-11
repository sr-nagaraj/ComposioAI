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
    authentication_breakdown: dict[str, int] = Field(default_factory=dict)
    api_type_breakdown: dict[str, int] = Field(default_factory=dict)
    sdk_breakdown: dict[str, int] = Field(default_factory=dict)
    mcp_breakdown: dict[str, int] = Field(default_factory=dict)
    buildability_breakdown: dict[str, int] = Field(default_factory=dict)
    blocker_breakdown: dict[str, int] = Field(default_factory=dict)
    confidence_distribution: dict[str, int] = Field(default_factory=dict)
    top_categories: dict[str, int] = Field(default_factory=dict)
    self_serve_count: int = Field(default=0, ge=0)
    gated_count: int = Field(default=0, ge=0)
    admin_required_count: int = Field(default=0, ge=0)
    partnership_required_count: int = Field(default=0, ge=0)
    research_success_rate: float = Field(default=0.0, ge=0, le=1)
    verification_success_rate: float = Field(default=0.0, ge=0, le=1)
    insights: list[str] = Field(default_factory=list)
    top_flagged_apps: list[str] = Field(default_factory=list)
    app_summaries: list[AppSummary] = Field(default_factory=list)
    generated_at: datetime
