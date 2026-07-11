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


def test_engine_builds_research_insight_breakdowns() -> None:
    research = [
        ResearchResult(
            app_name="Slack",
            status=ResearchStatus.SUCCESS,
            summary="Team collaboration platform.",
            category="Communication",
            confidence_score=0.92,
            researched_at=datetime.now(UTC),
            raw_agent_metadata={
                "authentication": "OAuth 2.0 with scopes",
                "api_type": "REST API",
                "sdk_available": "Official SDKs are available",
                "existing_mcp": "Unknown",
                "buildability": "High",
                "main_blocker": "OAuth scopes",
            },
        ),
        ResearchResult(
            app_name="LegacyCRM",
            status=ResearchStatus.PARTIAL,
            summary="CRM platform.",
            category="CRM",
            confidence_score=0.55,
            researched_at=datetime.now(UTC),
            raw_agent_metadata={
                "authentication": "API key",
                "api_type": "SOAP",
                "sdk_available": "No official SDK",
                "existing_mcp": "No",
                "buildability": "Low",
                "main_blocker": "Admin approval required",
            },
        ),
    ]
    verification = [
        VerificationResult(
            app_name="Slack",
            research_result_ref="Slack",
            verification_status=VerificationStatus.VERIFIED,
            confidence_score=0.9,
            verified_at=datetime.now(UTC),
        )
    ]

    analytics = AnalyticsEngine().build(research, verification)

    assert analytics.authentication_breakdown == {"OAuth2": 1, "API Key": 1}
    assert analytics.api_type_breakdown == {"REST": 1, "SOAP": 1}
    assert analytics.sdk_breakdown == {"Yes": 1, "No": 1}
    assert analytics.mcp_breakdown == {"Unknown": 1, "No": 1}
    assert analytics.buildability_breakdown == {"High": 1, "Low": 1}
    assert analytics.blocker_breakdown == {"OAuth": 1, "Admin Approval": 1}
    assert analytics.confidence_distribution == {
        "0.90+": 1,
        "0.80+": 0,
        "0.70+": 0,
        "0.60+": 0,
        "Below 0.60": 1,
    }
    assert analytics.top_categories == {"Communication": 1, "CRM": 1}
    assert analytics.self_serve_count == 1
    assert analytics.gated_count == 1
    assert analytics.admin_required_count == 1
    assert analytics.partnership_required_count == 0
    assert analytics.research_success_rate == 0.5
    assert analytics.verification_success_rate == 1.0
    assert 5 <= len(analytics.insights) <= 10
