"""Async verification agent orchestration.

The verification agent independently revisits the evidence cited by research,
extracts fresh verification data, compares it with the original metadata, and
returns an existing domain ``VerificationResult``.

Concrete Composio SDK/MCP calls are deliberately left as marked integration
points. Do not add SDK methods here until the current Composio API is confirmed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import ValidationError

from research_agent.domain.enums import EvidenceType, VerificationStatus
from research_agent.domain.research_models import Evidence, ResearchResult
from research_agent.domain.verification_models import VerificationResult

RawSource = Mapping[str, Any]
VerificationData = Mapping[str, Any]
FieldComparison = Mapping[str, Any]
VerificationReport = dict[str, Any]


class VerificationClient(Protocol):
    """Port for the concrete Composio/MCP verification workflow."""

    async def revisit_sources(self, research_result: ResearchResult) -> Sequence[RawSource]:
        """Fetch cited documentation independently of the research agent."""

    async def extract_verification_data(
        self,
        research_result: ResearchResult,
        sources: Sequence[RawSource],
    ) -> VerificationData:
        """Extract fresh metadata from revisited documentation."""


class Comparator(Protocol):
    """Port for field-level comparison logic implemented in ``comparator.py``."""

    def compare(
        self,
        original: Mapping[str, Any],
        verified: Mapping[str, Any],
    ) -> list[FieldComparison]:
        """Compare original and verified metadata field by field."""


class ConfidenceCalculator(Protocol):
    """Port for deterministic confidence scoring implemented in ``confidence.py``."""

    def score(
        self,
        comparisons: Sequence[FieldComparison],
        sources: Sequence[RawSource],
    ) -> Mapping[str, Any]:
        """Return overall confidence, per-field confidence, and status details."""


class VerificationCheckpointStore(Protocol):
    """Port for checkpoint persistence."""

    async def save(self, app_name: str, report: VerificationReport) -> None:
        """Persist verification progress for one app."""


@dataclass(frozen=True)
class RetryConfig:
    """Retry settings for transient verification failures."""

    max_attempts: int = 3
    initial_delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0


class VerificationAgent:
    """Verify research outputs without trusting the research agent's claims."""

    def __init__(
        self,
        verification_client: VerificationClient | None = None,
        comparator: Comparator | None = None,
        confidence_calculator: ConfidenceCalculator | None = None,
        checkpoint_store: VerificationCheckpointStore | None = None,
        retry_config: RetryConfig | None = None,
        timeout_seconds: float = 60.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._verification_client = verification_client
        self._comparator = comparator
        self._confidence_calculator = confidence_calculator
        self._checkpoint_store = checkpoint_store
        self._retry_config = retry_config or RetryConfig()
        self._timeout_seconds = timeout_seconds
        self._logger = logger or logging.getLogger(__name__)

    async def verify_all(self, research_results: Sequence[ResearchResult]) -> list[VerificationResult]:
        """Verify all research results and continue after per-app failures."""

        self._logger.info(
            "Verification batch started",
            extra={"app_count": len(research_results)},
        )

        verification_results: list[VerificationResult] = []
        for research_result in research_results:
            try:
                verification_results.append(await self.verify_app(research_result))
            except Exception as error:
                self._logger.exception(
                    "Unexpected verification failure",
                    extra={
                        "app_name": research_result.app_name,
                        "error_type": type(error).__name__,
                    },
                )
                verification_results.append(self._build_failure_result(research_result, error))

        self._logger.info(
            "Verification batch completed",
            extra={"app_count": len(research_results), "verified_count": len(verification_results)},
        )
        return verification_results

    async def verify_app(self, research_result: ResearchResult) -> VerificationResult:
        """Verify one research result by revisiting sources and comparing claims."""

        app_name = research_result.app_name
        self._logger.info("Verification started", extra={"app_name": app_name})

        try:
            sources = await self._with_retries(
                lambda: self.revisit_sources(research_result),
                step_name="revisit_sources",
                app_name=app_name,
            )
            if not sources:
                self._logger.warning("Missing documentation", extra={"app_name": app_name})

            verified_data = await self._with_retries(
                lambda: self.extract_verification_data(research_result, sources),
                step_name="extract_verification_data",
                app_name=app_name,
            )
            comparisons = self.compare_with_original(research_result, verified_data)
            report = self.generate_report(research_result, comparisons, sources)
            result = self._build_result_from_report(research_result, report, sources)
        except Exception as error:
            self._logger.exception(
                "Verification failed",
                extra={"app_name": app_name, "error_type": type(error).__name__},
            )
            result = self._build_failure_result(research_result, error)
            report = self._failure_report(research_result, error)

        await self._save_checkpoint(app_name, report)
        self._logger.info(
            "Verification completed",
            extra={
                "app_name": app_name,
                "final_status": result.verification_status.value,
                "confidence": result.confidence_score,
            },
        )
        return result

    async def revisit_sources(self, research_result: ResearchResult) -> Sequence[RawSource]:
        """Revisit cited documentation through the injected verification client."""

        if self._verification_client is not None:
            return await self._run_with_timeout(
                self._verification_client.revisit_sources(research_result)
            )

        # =====================================
        # COMPOSIO VERIFICATION INTEGRATION
        # =====================================
        raise NotImplementedError("Integrate Composio verification workflow here.")

    async def extract_verification_data(
        self,
        research_result: ResearchResult,
        sources: Sequence[RawSource],
    ) -> VerificationData:
        """Extract independent verification metadata from revisited sources."""

        if self._verification_client is not None:
            return await self._run_with_timeout(
                self._verification_client.extract_verification_data(research_result, sources)
            )

        # =====================================
        # COMPOSIO VERIFICATION INTEGRATION
        # =====================================
        raise NotImplementedError("Integrate Composio verification workflow here.")

    def compare_with_original(
        self,
        research_result: ResearchResult,
        verified_data: VerificationData,
    ) -> list[FieldComparison]:
        """Compare original research metadata with independently verified data."""

        original_metadata = self._original_metadata(research_result)
        if self._comparator is None:
            raise NotImplementedError("Inject comparator.py comparison logic here.")

        comparisons = self._comparator.compare(original_metadata, verified_data)
        conflicts = [
            comparison
            for comparison in comparisons
            if str(comparison.get("status", "")).lower() == "mismatch"
        ]
        if conflicts:
            self._logger.warning(
                "Verification conflicts detected",
                extra={"app_name": research_result.app_name, "conflict_count": len(conflicts)},
            )
        return comparisons

    def generate_report(
        self,
        research_result: ResearchResult,
        comparisons: Sequence[FieldComparison],
        sources: Sequence[RawSource],
    ) -> VerificationReport:
        """Generate a JSON-serializable verification report."""

        if self._confidence_calculator is None:
            raise NotImplementedError("Inject confidence.py scoring logic here.")

        confidence = dict(self._confidence_calculator.score(comparisons, sources))
        overall_confidence = self._confidence_to_percent(confidence.get("overall_confidence"))
        verification_status = self._coerce_status(confidence.get("verification_status"))
        human_review_required = bool(confidence.get("human_review_required", False))
        per_field_confidence = confidence.get("per_field_confidence", {})

        self._logger.info(
            "Confidence calculated",
            extra={
                "app_name": research_result.app_name,
                "overall_confidence": overall_confidence,
                "verification_status": verification_status.value,
                "human_review_required": human_review_required,
            },
        )

        fields = [
            self._field_report_item(comparison, per_field_confidence)
            for comparison in comparisons
        ]

        report: VerificationReport = {
            "app_name": research_result.app_name,
            "overall_status": verification_status.value,
            "overall_confidence": overall_confidence,
            "fields": fields,
            "human_review_required": human_review_required,
        }
        return report

    async def _with_retries(
        self,
        operation: Callable[[], Awaitable[Any]],
        *,
        step_name: str,
        app_name: str,
    ) -> Any:
        delay = self._retry_config.initial_delay_seconds
        last_error: Exception | None = None

        for attempt in range(1, self._retry_config.max_attempts + 1):
            try:
                return await self._run_with_timeout(operation())
            except Exception as error:
                last_error = error
                if attempt >= self._retry_config.max_attempts:
                    break

                self._logger.warning(
                    "Verification step failed; retrying",
                    extra={
                        "app_name": app_name,
                        "step_name": step_name,
                        "attempt": attempt,
                        "retry_delay_seconds": delay,
                        "error_type": type(error).__name__,
                    },
                )
                await asyncio.sleep(delay)
                delay *= self._retry_config.backoff_multiplier

        if last_error is None:
            raise RuntimeError(f"{step_name} failed without an exception")
        raise last_error

    async def _run_with_timeout(self, operation: Awaitable[Any]) -> Any:
        return await asyncio.wait_for(operation, timeout=self._timeout_seconds)

    async def _save_checkpoint(self, app_name: str, report: VerificationReport) -> None:
        if self._checkpoint_store is None:
            return

        try:
            await self._run_with_timeout(self._checkpoint_store.save(app_name, report))
        except Exception as error:
            self._logger.exception(
                "Failed to save verification checkpoint",
                extra={"app_name": app_name, "error_type": type(error).__name__},
            )

    def _build_result_from_report(
        self,
        research_result: ResearchResult,
        report: VerificationReport,
        sources: Sequence[RawSource],
    ) -> VerificationResult:
        discrepancies = [
            f"{field.get('field')}: {field.get('original')} != {field.get('verified')}"
            for field in report.get("fields", [])
            if str(field.get("status", "")).lower() == "mismatch"
        ]

        try:
            return VerificationResult(
                app_name=research_result.app_name,
                research_result_ref=research_result.app_name,
                verification_status=self._coerce_status(report.get("overall_status")),
                confidence_score=self._confidence_to_ratio(report.get("overall_confidence")),
                discrepancies=discrepancies,
                supporting_evidence=self._build_evidence(sources),
                verified_at=datetime.now(UTC),
            )
        except ValidationError as error:
            self._logger.exception(
                "VerificationResult validation failed",
                extra={"app_name": research_result.app_name, "error_type": type(error).__name__},
            )
            return self._build_failure_result(research_result, error)

    def _build_failure_result(
        self,
        research_result: ResearchResult,
        error: Exception,
    ) -> VerificationResult:
        return VerificationResult(
            app_name=research_result.app_name,
            research_result_ref=research_result.app_name,
            verification_status=VerificationStatus.UNVERIFIED,
            confidence_score=0.0,
            discrepancies=[f"{type(error).__name__}: {error}"],
            supporting_evidence=[],
            verified_at=datetime.now(UTC),
        )

    def _failure_report(
        self,
        research_result: ResearchResult,
        error: Exception,
    ) -> VerificationReport:
        return {
            "app_name": research_result.app_name,
            "overall_status": VerificationStatus.UNVERIFIED.value,
            "overall_confidence": 0,
            "fields": [],
            "human_review_required": True,
            "error": str(error),
            "error_type": type(error).__name__,
        }

    def _field_report_item(
        self,
        comparison: FieldComparison,
        per_field_confidence: Any,
    ) -> dict[str, Any]:
        field_name = str(comparison.get("field", "Unknown"))
        confidence = 0
        if isinstance(per_field_confidence, Mapping):
            confidence = self._confidence_to_percent(per_field_confidence.get(field_name))

        evidence = comparison.get("evidence", [])
        if isinstance(evidence, str):
            evidence = [evidence]
        if not isinstance(evidence, Sequence):
            evidence = []

        return {
            "field": field_name,
            "original": comparison.get("original", "Unknown"),
            "verified": comparison.get("verified", "Unknown"),
            "status": comparison.get("status", "Human Review Required"),
            "confidence": confidence,
            "evidence": list(evidence),
        }

    def _original_metadata(self, research_result: ResearchResult) -> dict[str, Any]:
        metadata = dict(research_result.raw_agent_metadata or {})
        metadata.setdefault("category", research_result.category or "Unknown")
        metadata.setdefault("description", research_result.summary or "Unknown")
        metadata.setdefault(
            "evidence_urls",
            [str(url) for url in research_result.documentation_urls],
        )
        return metadata

    def _build_evidence(self, sources: Sequence[RawSource]) -> list[Evidence]:
        evidence: list[Evidence] = []
        seen_urls: set[str] = set()

        for source in sources:
            raw_url = source.get("url")
            if raw_url is None:
                continue
            url = str(raw_url).strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            excerpt = str(source.get("excerpt") or source.get("content") or "Verified source.")
            try:
                evidence.append(
                    Evidence(
                        source_url=url,
                        source_type=EvidenceType.OFFICIAL_DOCS,
                        excerpt=excerpt[:1000],
                        relevance_score=self._confidence_to_ratio(source.get("confidence", 1.0)),
                        retrieved_at=datetime.now(UTC),
                    )
                )
            except ValidationError:
                self._logger.warning("Skipping invalid verification evidence", extra={"url": url})

        return evidence

    def _coerce_status(self, value: Any) -> VerificationStatus:
        if isinstance(value, VerificationStatus):
            return value

        normalized = str(value or "").strip().lower().replace(" ", "_")
        status_by_value = {status.value: status for status in VerificationStatus}
        if normalized in status_by_value:
            return status_by_value[normalized]
        if normalized == "human_review_required":
            return VerificationStatus.PARTIALLY_VERIFIED
        return VerificationStatus.UNVERIFIED

    def _confidence_to_ratio(self, value: Any) -> float:
        if isinstance(value, int | float):
            numeric_value = float(value)
            if numeric_value > 1:
                numeric_value = numeric_value / 100
            return min(max(numeric_value, 0.0), 1.0)
        return 0.0

    def _confidence_to_percent(self, value: Any) -> int:
        return round(self._confidence_to_ratio(value) * 100)
