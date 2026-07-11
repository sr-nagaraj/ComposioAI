"""Pure analytics computation over pipeline outputs."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from research_agent.domain.analytics_models import Analytics, AppSummary
from research_agent.domain.enums import ResearchStatus, VerificationStatus
from research_agent.domain.research_models import ResearchResult
from research_agent.domain.verification_models import VerificationResult

UNKNOWN = "Unknown"
CONFIDENCE_BUCKETS = ("0.90+", "0.80+", "0.70+", "0.60+", "Below 0.60")


@dataclass(frozen=True)
class AccessPatternCounts:
    """Self-serve and gated access counts inferred from research metadata."""

    self_serve: int
    gated: int
    admin_required: int
    partnership_required: int


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
        authentication_breakdown = Counter(
            self._normalize_authentication(self._metadata_value(result, "authentication"))
            for result in research_results
        )
        api_type_breakdown = Counter(
            self._normalize_api_type(self._metadata_value(result, "api_type"))
            for result in research_results
        )
        sdk_breakdown = Counter(
            self._normalize_sdk(self._metadata_value(result, "sdk_available"))
            for result in research_results
        )
        mcp_breakdown = Counter(
            self._normalize_sdk(self._metadata_value(result, "existing_mcp"))
            for result in research_results
        )
        buildability_breakdown = Counter(
            self._normalize_buildability(self._metadata_value(result, "buildability"))
            for result in research_results
        )
        blocker_breakdown = Counter(
            self._normalize_blocker(self._metadata_value(result, "main_blocker"))
            for result in research_results
        )
        confidence_distribution = Counter(
            self._confidence_bucket(result.confidence_score) for result in research_results
        )
        access_patterns = self._access_pattern_counts(research_results)
        research_success_rate = self._success_rate(
            result.status is ResearchStatus.SUCCESS for result in research_results
        )
        verification_success_rate = self._success_rate(
            result.verification_status is VerificationStatus.VERIFIED
            for result in verification_results
        )
        top_categories = dict(categories.most_common(5))

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
            authentication_breakdown=dict(authentication_breakdown),
            api_type_breakdown=dict(api_type_breakdown),
            sdk_breakdown=dict(sdk_breakdown),
            mcp_breakdown=dict(mcp_breakdown),
            buildability_breakdown=dict(buildability_breakdown),
            blocker_breakdown=dict(blocker_breakdown),
            confidence_distribution=self._ordered_distribution(confidence_distribution),
            top_categories=top_categories,
            self_serve_count=access_patterns.self_serve,
            gated_count=access_patterns.gated,
            admin_required_count=access_patterns.admin_required,
            partnership_required_count=access_patterns.partnership_required,
            research_success_rate=research_success_rate,
            verification_success_rate=verification_success_rate,
            insights=self._generate_insights(
                total_apps=len(research_results),
                authentication_breakdown=authentication_breakdown,
                api_type_breakdown=api_type_breakdown,
                sdk_breakdown=sdk_breakdown,
                mcp_breakdown=mcp_breakdown,
                buildability_breakdown=buildability_breakdown,
                blocker_breakdown=blocker_breakdown,
                access_patterns=access_patterns,
                research_success_rate=research_success_rate,
                verification_success_rate=verification_success_rate,
                top_categories=top_categories,
            ),
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

    def _metadata_value(self, result: ResearchResult, key: str) -> Any:
        metadata = result.raw_agent_metadata or {}
        return metadata.get(key, UNKNOWN)

    def _normalize_authentication(self, value: Any) -> str:
        text = self._normalized_text(value)
        if text == "unknown":
            return UNKNOWN
        if "oauth" in text or "open authorization" in text:
            return "OAuth2"
        if "api key" in text or "apikey" in text or "token key" in text:
            return "API Key"
        if "bearer" in text:
            return "Bearer Token"
        if "basic" in text:
            return "Basic"
        if "jwt" in text or "json web token" in text:
            return "JWT"
        if "session" in text or "cookie" in text:
            return "Session"
        return UNKNOWN

    def _normalize_api_type(self, value: Any) -> str:
        text = self._normalized_text(value)
        has_rest = "rest" in text or "http api" in text
        has_graphql = "graphql" in text or "graph ql" in text
        if has_rest and has_graphql:
            return "REST + GraphQL"
        if has_graphql:
            return "GraphQL"
        if has_rest:
            return "REST"
        if "soap" in text:
            return "SOAP"
        if "rpc" in text or "grpc" in text or "json-rpc" in text:
            return "RPC"
        return UNKNOWN

    def _normalize_sdk(self, value: Any) -> str:
        text = self._normalized_text(value)
        if text in {"yes", "true", "available", "supported"}:
            return "Yes"
        if text in {"no", "false", "none", "not available", "unsupported"}:
            return "No"
        if any(marker in text for marker in ("no official", "not provided", "unavailable")):
            return "No"
        if any(marker in text for marker in ("sdk", "client library", "libraries")):
            return "Yes"
        return UNKNOWN

    def _normalize_buildability(self, value: Any) -> str:
        text = self._normalized_text(value)
        if "high" in text or "easy" in text or "straightforward" in text:
            return "High"
        if "medium" in text or "moderate" in text or "partial" in text:
            return "Medium"
        if "low" in text or "hard" in text or "difficult" in text or "blocked" in text:
            return "Low"
        return UNKNOWN

    def _normalize_blocker(self, value: Any) -> str:
        text = self._normalized_text(value)
        if text == "unknown" or text in {"none", "no blocker", "n/a", "na"}:
            return UNKNOWN
        if "oauth" in text or "scope" in text or "permission" in text:
            return "OAuth"
        if "workspace" in text or "sso" in text or "sign-in" in text or "signin" in text:
            return "Workspace Sign-in"
        if "admin" in text or "approval" in text or "administrator" in text:
            return "Admin Approval"
        if "marketplace" in text or "app review" in text or "review" in text:
            return "Marketplace Review"
        if "rate limit" in text or "quota" in text or "throttle" in text:
            return "Rate Limits"
        if "partner" in text or "partnership" in text:
            return "Partner Program"
        if "paid" in text or "enterprise plan" in text or "pricing" in text:
            return "Paid Plan"
        return UNKNOWN

    def _access_pattern_counts(self, results: list[ResearchResult]) -> AccessPatternCounts:
        self_serve = 0
        gated = 0
        admin_required = 0
        partnership_required = 0

        for result in results:
            authentication = self._normalize_authentication(
                self._metadata_value(result, "authentication")
            )
            buildability = self._normalize_buildability(
                self._metadata_value(result, "buildability")
            )
            blocker = self._normalize_blocker(self._metadata_value(result, "main_blocker"))

            is_admin_required = blocker in {"Admin Approval", "Workspace Sign-in"}
            is_partnership_required = blocker in {"Partner Program", "Marketplace Review"}
            is_gated = (
                is_admin_required
                or is_partnership_required
                or blocker in {"Paid Plan", "Rate Limits"}
                or buildability == "Low"
            )

            admin_required += int(is_admin_required)
            partnership_required += int(is_partnership_required)
            gated += int(is_gated)
            if not is_gated and authentication != UNKNOWN and buildability in {"High", "Medium"}:
                self_serve += 1

        return AccessPatternCounts(
            self_serve=self_serve,
            gated=gated,
            admin_required=admin_required,
            partnership_required=partnership_required,
        )

    def _confidence_bucket(self, confidence: float) -> str:
        if confidence >= 0.9:
            return "0.90+"
        if confidence >= 0.8:
            return "0.80+"
        if confidence >= 0.7:
            return "0.70+"
        if confidence >= 0.6:
            return "0.60+"
        return "Below 0.60"

    def _ordered_distribution(self, counter: Counter[str]) -> dict[str, int]:
        return {bucket: counter[bucket] for bucket in CONFIDENCE_BUCKETS}

    def _success_rate(self, values: Iterable[bool]) -> float:
        outcomes = list(values)
        if not outcomes:
            return 0.0
        return sum(1 for value in outcomes if value) / len(outcomes)

    def _generate_insights(
        self,
        *,
        total_apps: int,
        authentication_breakdown: Counter[str],
        api_type_breakdown: Counter[str],
        sdk_breakdown: Counter[str],
        mcp_breakdown: Counter[str],
        buildability_breakdown: Counter[str],
        blocker_breakdown: Counter[str],
        access_patterns: AccessPatternCounts,
        research_success_rate: float,
        verification_success_rate: float,
        top_categories: dict[str, int],
    ) -> list[str]:
        if total_apps == 0:
            return ["No applications were available for analytics."]

        insights = [
            self._dominant_counter_insight(
                authentication_breakdown,
                "authentication mechanism",
            ),
            self._dominant_counter_insight(api_type_breakdown, "API type"),
            self._dominant_counter_insight(buildability_breakdown, "buildability tier"),
        ]

        sdk_yes = sdk_breakdown["Yes"]
        if sdk_yes:
            insights.append(
                f"Official SDKs are available for {sdk_yes} of {total_apps} researched apps."
            )

        mcp_yes = mcp_breakdown["Yes"]
        mcp_unknown = mcp_breakdown[UNKNOWN]
        if mcp_yes:
            insights.append(f"Existing MCP support was found for {mcp_yes} apps.")
        elif mcp_unknown:
            insights.append("Existing MCP support is mostly unknown or uncommon in the sample.")

        if access_patterns.self_serve >= access_patterns.gated:
            insights.append(
                f"Self-service access appears more common, with "
                f"{access_patterns.self_serve} self-serve apps versus "
                f"{access_patterns.gated} gated apps."
            )
        else:
            insights.append(
                f"Gated access appears more common, with {access_patterns.gated} gated apps."
            )

        top_blocker = self._top_known_item(blocker_breakdown)
        if top_blocker is not None:
            blocker, count = top_blocker
            insights.append(f"{blocker} is the most common blocker, affecting {count} apps.")

        if top_categories:
            category, count = next(iter(top_categories.items()))
            insights.append(f"{category} is the largest category with {count} apps.")

        insights.append(f"Research success rate is {self._percentage(research_success_rate)}.")
        insights.append(
            f"Verification success rate is {self._percentage(verification_success_rate)}."
        )
        return [insight for insight in insights if insight][:10]

    def _dominant_counter_insight(self, counter: Counter[str], label: str) -> str:
        top_item = self._top_known_item(counter)
        if top_item is None:
            return f"No dominant {label} was identified."
        value, count = top_item
        return f"{value} is the dominant {label}, appearing in {count} apps."

    def _top_known_item(self, counter: Counter[str]) -> tuple[str, int] | None:
        for value, count in counter.most_common():
            if value != UNKNOWN and count > 0:
                return value, count
        return None

    def _normalized_text(self, value: Any) -> str:
        if value is None:
            return "unknown"
        if isinstance(value, list):
            value = " ".join(str(item) for item in value)
        text = str(value).strip().lower()
        return text or "unknown"

    def _percentage(self, value: float) -> str:
        return f"{value * 100:.0f}%"
