"""Pure analytics computation over pipeline outputs."""

from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime

from research_agent.domain.analytics_models import Analytics, AppSummary
from research_agent.domain.enums import VerificationStatus
from research_agent.domain.research_models import ResearchResult
from research_agent.domain.verification_models import VerificationResult


class AnalyticsEngine:
    """Build aggregate analytics from research and verification results."""

    def build(
        self,
        research_results: list[ResearchResult],
        verification_results: list[VerificationResult],
    ) -> Analytics:
        verification_by_app = {item.app_name: item for item in verification_results}
        summaries = [
            self._build_summary(result, verification_by_app.get(result.app_name))
            for result in research_results
        ]
        verification_counts = Counter(item.verification_status for item in verification_results)
        categories = Counter(result.category or "Uncategorized" for result in research_results)

        return Analytics(
            total_apps=len(research_results),
            verified_count=verification_counts[VerificationStatus.VERIFIED],
            partially_verified_count=verification_counts[VerificationStatus.PARTIALLY_VERIFIED],
            unverified_count=verification_counts[VerificationStatus.UNVERIFIED],
            contradicted_count=verification_counts[VerificationStatus.CONTRADICTED],
            average_research_confidence=self._average(
                result.confidence_score for result in research_results
            ),
            average_verification_confidence=self._average(
                result.confidence_score for result in verification_results
            ),
            category_breakdown=dict(categories),
            top_flagged_apps=[summary.app_name for summary in summaries if summary.flags][:10],
            app_summaries=summaries,
            generated_at=datetime.now(UTC),
        )

    def _build_summary(
        self,
        research: ResearchResult,
        verification: VerificationResult | None,
    ) -> AppSummary:
        flags: list[str] = []
        verification_confidence = verification.confidence_score if verification else 0.0
        overall_status = verification.verification_status.value if verification else "not_verified"

        if research.confidence_score < 0.5:
            flags.append("low research confidence")
        if verification and verification.confidence_score < 0.5:
            flags.append("low verification confidence")
        if verification and verification.verification_status is VerificationStatus.CONTRADICTED:
            flags.append("contradicted evidence")

        return AppSummary(
            app_name=research.app_name,
            category=research.category,
            overall_status=overall_status,
            research_confidence=research.confidence_score,
            verification_confidence=verification_confidence,
            key_findings=[research.summary] if research.summary else [],
            flags=flags,
        )

    def _average(self, values: Iterable[float]) -> float:
        numeric_values = list(values)
        if not numeric_values:
            return 0.0
        return sum(numeric_values) / len(numeric_values)
