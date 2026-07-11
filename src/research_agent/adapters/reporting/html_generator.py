"""Jinja2 HTML case-study report generator."""

from collections import Counter
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from config.constants import DEFAULT_TEMPLATE_NAME
from research_agent.domain.analytics_models import Analytics
from research_agent.domain.research_models import ResearchResult
from research_agent.domain.verification_models import VerificationResult

UNKNOWN = "Unknown"
VERIFY_FIELDS = (
    "category",
    "description",
    "authentication",
    "api_type",
    "sdk_available",
    "existing_mcp",
    "buildability",
    "main_blocker",
)


class HtmlGenerator:
    """Render final HTML reports from analytics data."""

    def __init__(self, template_dir: Path | None = None) -> None:
        self._template_dir = template_dir or Path(__file__).parent / "templates"
        self._environment = Environment(
            loader=FileSystemLoader(self._template_dir),
            autoescape=select_autoescape(("html", "xml")),
        )

    async def render(
        self,
        *,
        research_results: list[ResearchResult],
        verification_results: list[VerificationResult],
        analytics: Analytics,
        output_path: Path,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        template = self._environment.get_template(DEFAULT_TEMPLATE_NAME)
        html = template.render(
            **self._template_context(
                research_results=research_results,
                verification_results=verification_results,
                analytics=analytics,
            )
        )
        output_path.write_text(html, encoding="utf-8")
        return output_path

    def _template_context(
        self,
        *,
        research_results: list[ResearchResult],
        verification_results: list[VerificationResult],
        analytics: Analytics,
    ) -> dict[str, Any]:
        verification_by_app = {item.app_name: item for item in verification_results}
        app_rows = [
            self._app_row(result, verification_by_app.get(result.app_name))
            for result in research_results
        ]
        chart_configs = self._chart_configs(analytics)
        return {
            "analytics": analytics,
            "research_results": research_results,
            "verification_results": verification_results,
            "app_rows": app_rows,
            "hero_metrics": self._hero_metrics(analytics),
            "dashboard_metrics": self._dashboard_metrics(analytics),
            "executive_insights": self._executive_insights(analytics),
            "architecture_steps": self._architecture_steps(),
            "workflow_steps": self._workflow_steps(),
            "verification_steps": self._verification_steps(),
            "limitations": self._limitations(),
            "tech_stack": self._tech_stack(),
            "footer": {
                "github_repository": "Project repository",
                "architecture_document": "docs/architecture.md",
            },
            "generated_time": self._datetime_text(analytics.generated_at),
            "average_research_confidence": self._percent(analytics.average_research_confidence),
            "average_verification_confidence": self._percent(
                analytics.average_verification_confidence
            ),
            "verification_review_count": len(verification_results),
            "field_status_counts": self._field_status_counts(verification_results),
            "charts": [{"id": chart["id"], "title": chart["title"]} for chart in chart_configs],
            "chart_configs": chart_configs,
        }

    def _hero_metrics(self, analytics: Analytics) -> list[dict[str, str]]:
        return [
            {"label": "Apps researched", "value": str(analytics.total_apps)},
            {"label": "Verified", "value": str(analytics.verified_count)},
            {
                "label": "Average Confidence",
                "value": self._percent(analytics.average_verification_confidence),
            },
            {"label": "Runtime", "value": "AsyncIO"},
            {"label": "Categories", "value": str(len(analytics.category_breakdown))},
        ]

    def _dashboard_metrics(self, analytics: Analytics) -> list[dict[str, str]]:
        return [
            {"label": "Total Apps", "value": str(analytics.total_apps)},
            {"label": "Verified", "value": str(analytics.verified_count)},
            {"label": "Partial", "value": str(analytics.partially_verified_count)},
            {"label": "Unverified", "value": str(analytics.unverified_count)},
            {
                "label": "Average Research Confidence",
                "value": self._percent(analytics.average_research_confidence),
            },
            {
                "label": "Average Verification Confidence",
                "value": self._percent(analytics.average_verification_confidence),
            },
            {"label": "Categories", "value": str(len(analytics.category_breakdown))},
        ]

    def _executive_insights(self, analytics: Analytics) -> list[str]:
        if analytics.insights:
            return analytics.insights[:6]
        return [
            "Research completed, but no aggregate insights were generated.",
            "Unknown values indicate fields without official documentation evidence.",
        ]

    def _chart_configs(self, analytics: Analytics) -> list[dict[str, Any]]:
        verification_status = {
            "Verified": analytics.verified_count,
            "Partial": analytics.partially_verified_count,
            "Unverified": analytics.unverified_count,
            "Contradicted": analytics.contradicted_count,
        }
        access = {
            "Self Serve": analytics.self_serve_count,
            "Gated": analytics.gated_count,
            "Admin Required": analytics.admin_required_count,
            "Partnership Required": analytics.partnership_required_count,
        }
        chart_sources = [
            ("authChart", "Authentication Breakdown", analytics.authentication_breakdown, "doughnut"),
            ("apiChart", "API Types", analytics.api_type_breakdown, "bar"),
            ("verificationChart", "Verification Status", verification_status, "doughnut"),
            ("categoryChart", "Category Breakdown", analytics.category_breakdown, "bar"),
            ("buildabilityChart", "Buildability", analytics.buildability_breakdown, "bar"),
            (
                "confidenceChart",
                "Confidence Distribution",
                analytics.confidence_distribution,
                "bar",
            ),
            ("blockerChart", "Top Blockers", analytics.blocker_breakdown, "bar"),
            ("accessChart", "Self Serve vs Gated", access, "doughnut"),
        ]
        return [
            {
                "id": chart_id,
                "title": title,
                "type": chart_type,
                "labels": list(data.keys()),
                "values": list(data.values()),
            }
            for chart_id, title, data, chart_type in chart_sources
        ]

    def _app_row(
        self,
        research: ResearchResult,
        verification: VerificationResult | None,
    ) -> dict[str, Any]:
        metadata = research.raw_agent_metadata or {}
        verification_status = (
            verification.verification_status.value.replace("_", " ").title()
            if verification
            else "Not Verified"
        )
        field_results = verification.field_results if verification else {}
        discrepancies = verification.discrepancies if verification else []
        supporting_evidence = verification.supporting_evidence if verification else []
        sdk = self._metadata_text(metadata, "sdk_available")
        mcp = self._metadata_text(metadata, "existing_mcp")
        buildability = self._metadata_text(metadata, "buildability")
        main_blocker = self._metadata_text(metadata, "main_blocker")

        return {
            "app_name": research.app_name,
            "category": research.category or UNKNOWN,
            "description": research.summary or self._metadata_text(metadata, "description"),
            "authentication": self._metadata_text(metadata, "authentication"),
            "access_model": self._access_model(buildability, main_blocker),
            "api_type": self._metadata_text(metadata, "api_type"),
            "sdk_available": sdk,
            "existing_mcp": mcp,
            "buildability": buildability,
            "main_blocker": main_blocker,
            "research_confidence": self._percent(research.confidence_score),
            "verification_status": verification_status,
            "verification_confidence": self._percent(verification.confidence_score)
            if verification
            else "0%",
            "verification_class": self._badge_class(verification_status),
            "sdk_class": self._badge_class(sdk),
            "mcp_class": self._badge_class(mcp),
            "buildability_class": self._badge_class(buildability),
            "evidence_urls": [str(url) for url in research.documentation_urls],
            "discrepancies": discrepancies,
            "supporting_evidence": [
                {
                    "url": str(item.source_url),
                    "excerpt": item.excerpt,
                    "score": self._percent(item.relevance_score),
                }
                for item in supporting_evidence
            ],
            "field_results": [
                {
                    "field": field.replace("_", " ").title(),
                    "status": field_results.get(field, UNKNOWN),
                    "class": self._badge_class(field_results.get(field, UNKNOWN)),
                }
                for field in VERIFY_FIELDS
            ],
        }

    def _field_status_counts(
        self,
        verification_results: list[VerificationResult],
    ) -> dict[str, int]:
        counts: Counter[str] = Counter({"PASS": 0, "FAIL": 0, "UNKNOWN": 0})
        for result in verification_results:
            counts.update(status.upper() for status in result.field_results.values())
        return {status: counts[status] for status in ("PASS", "FAIL", "UNKNOWN")}

    def _metadata_text(self, metadata: dict[str, Any], key: str) -> str:
        value = metadata.get(key, UNKNOWN)
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value if str(item).strip())
        text = str(value).strip()
        return text or UNKNOWN

    def _access_model(self, buildability: str, blocker: str) -> str:
        text = f"{buildability} {blocker}".lower()
        if any(marker in text for marker in ("admin", "partner", "marketplace", "paid", "low")):
            return "Gated"
        if text.strip() == "unknown unknown":
            return UNKNOWN
        return "Self Serve"

    def _badge_class(self, value: str) -> str:
        normalized = value.lower().replace("_", " ").strip()
        if normalized in {"verified", "pass", "high", "yes", "self serve"}:
            return "pass"
        if normalized in {"contradicted", "fail", "low", "no", "gated"}:
            return "fail"
        if normalized in {"partially verified", "partial", "medium"}:
            return "partial"
        return "unknown"

    def _architecture_steps(self) -> list[dict[str, str]]:
        return [
            {"title": "CSV", "description": "SaaS apps enter as structured rows."},
            {"title": "Research Agent", "description": "Finds official developer documentation."},
            {"title": "Official Docs", "description": "Evidence is constrained to primary sources."},
            {"title": "Verification Agent", "description": "Checks fields against cited docs."},
            {"title": "Analytics Engine", "description": "Aggregates patterns across apps."},
            {"title": "HTML Case Study", "description": "Presents findings for review."},
        ]

    def _workflow_steps(self) -> list[dict[str, str]]:
        return [
            {"title": "Read CSV", "description": "Load app names and optional hints."},
            {"title": "Discover Official Documentation", "description": "Search and fetch public docs."},
            {"title": "Extract Metadata", "description": "Create structured research JSON."},
            {"title": "Store Research Results", "description": "Persist evidence-backed fields."},
            {"title": "Verify Against Documentation", "description": "Validate every field."},
            {"title": "Generate Analytics", "description": "Summarize cross-app patterns."},
            {"title": "Generate HTML Report", "description": "Render this standalone case study."},
        ]

    def _verification_steps(self) -> list[dict[str, str]]:
        return [
            {"title": "Research Agent", "description": "Produces initial metadata."},
            {"title": "Verification Agent", "description": "Runs an independent evidence check."},
            {"title": "Official Documentation", "description": "Uses cited source text only."},
            {"title": "Field Validation", "description": "Marks PASS, FAIL, or UNKNOWN."},
            {"title": "Confidence Score", "description": "Rolls field confidence into an outcome."},
        ]

    def _limitations(self) -> list[str]:
        return [
            "The current report reflects the apps present in the generated pipeline artifacts.",
            "Larger runs should be chunked or checkpointed to control API cost and recovery time.",
            "Unknown values indicate lack of official evidence.",
            "No assumptions were made when documentation was missing.",
            "Verification relies only on official documentation.",
        ]

    def _tech_stack(self) -> list[str]:
        return [
            "Python",
            "Composio SDK",
            "OpenAI Responses API",
            "Jinja2",
            "AsyncIO",
            "Typer",
            "Pydantic",
            "Chart.js",
        ]

    def _percent(self, value: float) -> str:
        return f"{value * 100:.0f}%"

    def _datetime_text(self, value: Any) -> str:
        return value.strftime("%Y-%m-%d %H:%M UTC") if hasattr(value, "strftime") else str(value)
