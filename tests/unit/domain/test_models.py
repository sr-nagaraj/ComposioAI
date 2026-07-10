"""Basic domain model validation tests."""

from datetime import UTC, datetime

from research_agent.domain.enums import EvidenceType, ResearchStatus
from research_agent.domain.input_models import AppInput
from research_agent.domain.research_models import Evidence, ResearchResult


def test_app_input_accepts_minimum_required_fields() -> None:
    app = AppInput(name="Example", row_number=2)

    assert app.name == "Example"
    assert app.row_number == 2


def test_research_result_accepts_evidence() -> None:
    evidence = Evidence(
        source_url="https://example.com/docs",
        source_type=EvidenceType.OFFICIAL_DOCS,
        excerpt="Official documentation snippet.",
        relevance_score=0.9,
        retrieved_at=datetime.now(UTC),
    )

    result = ResearchResult(
        app_name="Example",
        status=ResearchStatus.SUCCESS,
        summary="Example app summary.",
        documentation_urls=["https://example.com/docs"],
        evidence=[evidence],
        confidence_score=0.8,
        researched_at=datetime.now(UTC),
    )

    assert result.evidence[0].source_type is EvidenceType.OFFICIAL_DOCS
