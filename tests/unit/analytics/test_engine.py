"""Analytics engine tests."""

from datetime import UTC, datetime

from research_agent.analytics.engine import AnalyticsEngine
from research_agent.domain.enums import ResearchStatus, VerificationStatus
from research_agent.domain.research_models import ResearchResult
from research_agent.domain.verification_models import VerificationResult


def test_engine_counts_verification_statuses() -> None:
    research = [
        ResearchResult(
            app_name="Example",
            status=ResearchStatus.SUCCESS,
            summary="Example app summary.",
            category="Docs",
            confidence_score=0.8,
            researched_at=datetime.now(UTC),
        )
    ]
    verification = [
        VerificationResult(
            app_name="Example",
            research_result_ref="Example",
            verification_status=VerificationStatus.VERIFIED,
            confidence_score=0.9,
            verified_at=datetime.now(UTC),
        )
    ]

    analytics = AnalyticsEngine().build(research, verification)

    assert analytics.total_apps == 1
    assert analytics.verified_count == 1
    assert analytics.category_breakdown == {"Docs": 1}
