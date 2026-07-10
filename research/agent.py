"""Async research agent orchestration with Composio integration points.

This module intentionally does not call concrete Composio SDK methods. The exact
SDK/MCP workflow should be wired through the injected client dependencies once
the current Composio API surface is confirmed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import ValidationError

from research_agent.domain.enums import EvidenceType, ResearchStatus
from research_agent.domain.research_models import Evidence, ResearchResult

RawSource = Mapping[str, Any]
Metadata = Mapping[str, Any]


class ResearchClient(Protocol):
    """Port for the concrete Composio/MCP research workflow."""

    async def initialize(self) -> None:
        """Prepare client connections, auth, or sessions."""

    async def search_official_docs(self, app_name: str) -> Sequence[RawSource]:
        """Find official developer documentation sources for an app."""

    async def collect_sources(self, app_name: str, sources: Sequence[RawSource]) -> Sequence[RawSource]:
        """Collect source content from documentation candidates."""

    async def extract_metadata(self, app_name: str, sources: Sequence[RawSource]) -> Metadata:
        """Extract structured metadata from collected source content."""


class CheckpointStore(Protocol):
    """Port for checkpoint persistence."""

    async def save(self, app_name: str, result: ResearchResult) -> None:
        """Persist research progress for one app."""


MetadataExtractor = Callable[[str, Sequence[RawSource], Metadata], Awaitable[Metadata]]


@dataclass(frozen=True)
class RetryConfig:
    """Retry settings for transient research failures."""

    max_attempts: int = 3
    initial_delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0


class ResearchAgent:
    """Research one application and return a normalized ``ResearchResult``."""

    def __init__(
        self,
        research_client: ResearchClient | None = None,
        checkpoint_store: CheckpointStore | None = None,
        metadata_extractor: MetadataExtractor | None = None,
        retry_config: RetryConfig | None = None,
        timeout_seconds: float = 60.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._research_client = research_client
        self._checkpoint_store = checkpoint_store
        self._metadata_extractor = metadata_extractor
        self._retry_config = retry_config or RetryConfig()
        self._timeout_seconds = timeout_seconds
        self._logger = logger or logging.getLogger(__name__)
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize injected research dependencies."""

        if self._initialized:
            return

        self._logger.info("Initializing research agent")
        if self._research_client is None:
            self._logger.warning("Research agent initialized without a Composio client")
            self._initialized = True
            return

        await self._run_with_timeout(self._research_client.initialize())
        self._initialized = True

    async def research_app(self, app_name: str) -> ResearchResult:
        """Research a single app and gracefully convert failures into a result."""

        normalized_app_name = app_name.strip()
        if not normalized_app_name:
            raise ValueError("app_name must not be empty")

        await self.initialize()
        self._logger.info("Starting app research", extra={"app_name": normalized_app_name})

        try:
            sources = await self._with_retries(
                lambda: self.search_official_docs(normalized_app_name),
                step_name="search_official_docs",
                app_name=normalized_app_name,
            )
            collected_sources = await self._with_retries(
                lambda: self.collect_sources(normalized_app_name, sources),
                step_name="collect_sources",
                app_name=normalized_app_name,
            )
            metadata = await self._with_retries(
                lambda: self.extract_metadata(normalized_app_name, collected_sources),
                step_name="extract_metadata",
                app_name=normalized_app_name,
            )
            result = self.build_result(normalized_app_name, metadata, collected_sources)
        except Exception as error:
            self._logger.exception(
                "Research failed",
                extra={"app_name": normalized_app_name, "error_type": type(error).__name__},
            )
            result = self._build_failure_result(normalized_app_name, error)

        await self.save_checkpoint(normalized_app_name, result)
        return result

    async def search_official_docs(self, app_name: str) -> Sequence[RawSource]:
        """Search for official developer documentation sources."""

        if self._research_client is not None:
            return await self._run_with_timeout(self._research_client.search_official_docs(app_name))

        # ====================================
        # COMPOSIO INTEGRATION START
        # ====================================
        raise NotImplementedError("Integrate Composio SDK research workflow here.")
        # ====================================
        # COMPOSIO INTEGRATION END
        # ====================================

    async def collect_sources(self, app_name: str, sources: Sequence[RawSource]) -> Sequence[RawSource]:
        """Collect official documentation source content."""

        if self._research_client is not None:
            return await self._run_with_timeout(
                self._research_client.collect_sources(app_name, sources)
            )

        # ====================================
        # COMPOSIO INTEGRATION START
        # ====================================
        raise NotImplementedError("Integrate Composio SDK source collection workflow here.")
        # ====================================
        # COMPOSIO INTEGRATION END
        # ====================================

    async def extract_metadata(self, app_name: str, sources: Sequence[RawSource]) -> Metadata:
        """Extract structured metadata from collected source content."""

        raw_metadata: Metadata
        if self._research_client is not None:
            raw_metadata = await self._run_with_timeout(
                self._research_client.extract_metadata(app_name, sources)
            )
        else:
            # ====================================
            # COMPOSIO INTEGRATION START
            # ====================================
            raise NotImplementedError("Integrate Composio SDK metadata extraction workflow here.")
            # ====================================
            # COMPOSIO INTEGRATION END
            # ====================================

        if self._metadata_extractor is None:
            return raw_metadata

        return await self._run_with_timeout(
            self._metadata_extractor(app_name, sources, raw_metadata)
        )

    def build_result(
        self,
        app_name: str,
        metadata: Metadata,
        sources: Sequence[RawSource],
    ) -> ResearchResult:
        """Build a domain ``ResearchResult`` from extracted metadata."""

        evidence = self._build_evidence(metadata, sources)
        documentation_urls = self._extract_documentation_urls(metadata, sources)
        confidence_score = self._coerce_confidence(metadata.get("confidence_score"))
        summary = self._unknown_if_missing(metadata.get("description"))
        category = self._optional_unknown(metadata.get("category"))

        status = ResearchStatus.SUCCESS
        if summary == "Unknown" or category == "Unknown" or confidence_score < 0.5:
            status = ResearchStatus.PARTIAL

        try:
            return ResearchResult(
                app_name=app_name,
                status=status,
                summary=summary,
                category=category,
                documentation_urls=documentation_urls,
                evidence=evidence,
                confidence_score=confidence_score,
                researched_at=datetime.now(UTC),
                raw_agent_metadata=dict(metadata),
            )
        except ValidationError as error:
            self._logger.exception(
                "ResearchResult validation failed",
                extra={"app_name": app_name, "error_type": type(error).__name__},
            )
            return self._build_failure_result(app_name, error, metadata=dict(metadata))

    async def save_checkpoint(self, app_name: str, result: ResearchResult) -> None:
        """Persist a checkpoint if checkpoint storage was injected."""

        if self._checkpoint_store is None:
            return

        try:
            await self._run_with_timeout(self._checkpoint_store.save(app_name, result))
        except Exception as error:
            self._logger.exception(
                "Failed to save research checkpoint",
                extra={"app_name": app_name, "error_type": type(error).__name__},
            )

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
                    "Research step failed; retrying",
                    extra={
                        "app_name": app_name,
                        "step_name": step_name,
                        "attempt": attempt,
                        "error_type": type(error).__name__,
                        "retry_delay_seconds": delay,
                    },
                )
                await asyncio.sleep(delay)
                delay *= self._retry_config.backoff_multiplier

        if last_error is None:
            raise RuntimeError(f"{step_name} failed without an exception")
        raise last_error

    async def _run_with_timeout(self, operation: Awaitable[Any]) -> Any:
        return await asyncio.wait_for(operation, timeout=self._timeout_seconds)

    def _build_evidence(self, metadata: Metadata, sources: Sequence[RawSource]) -> list[Evidence]:
        evidence_urls = metadata.get("evidence_urls")
        if not isinstance(evidence_urls, Sequence) or isinstance(evidence_urls, str):
            evidence_urls = [source.get("url") for source in sources]

        evidence: list[Evidence] = []
        seen_urls: set[str] = set()
        for raw_url in evidence_urls:
            url = self._optional_unknown(raw_url)
            if url == "Unknown" or url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                evidence.append(
                    Evidence(
                        source_url=url,
                        source_type=EvidenceType.OFFICIAL_DOCS,
                        excerpt=self._evidence_excerpt_for_url(url, sources),
                        relevance_score=self._coerce_confidence(metadata.get("confidence_score")),
                        retrieved_at=datetime.now(UTC),
                    )
                )
            except ValidationError:
                self._logger.warning("Skipping invalid evidence URL", extra={"url": url})

        return evidence

    def _extract_documentation_urls(
        self,
        metadata: Metadata,
        sources: Sequence[RawSource],
    ) -> list[str]:
        urls = metadata.get("evidence_urls")
        if not isinstance(urls, Sequence) or isinstance(urls, str):
            urls = [source.get("url") for source in sources]

        normalized_urls: list[str] = []
        seen_urls: set[str] = set()
        for raw_url in urls:
            url = self._optional_unknown(raw_url)
            if url == "Unknown" or url in seen_urls:
                continue
            seen_urls.add(url)
            normalized_urls.append(url)
        return normalized_urls

    def _evidence_excerpt_for_url(self, url: str, sources: Sequence[RawSource]) -> str:
        for source in sources:
            if source.get("url") == url:
                excerpt = self._optional_unknown(source.get("excerpt") or source.get("content"))
                return excerpt[:1000] if excerpt != "Unknown" else "Official documentation source."
        return "Official documentation source."

    def _build_failure_result(
        self,
        app_name: str,
        error: Exception,
        metadata: dict[str, Any] | None = None,
    ) -> ResearchResult:
        return ResearchResult(
            app_name=app_name,
            status=ResearchStatus.FAILED,
            summary="Unknown",
            category="Unknown",
            documentation_urls=[],
            evidence=[],
            confidence_score=0.0,
            researched_at=datetime.now(UTC),
            raw_agent_metadata={
                "error": str(error),
                "error_type": type(error).__name__,
                **(metadata or {}),
            },
        )

    def _coerce_confidence(self, value: Any) -> float:
        if isinstance(value, int | float):
            return min(max(float(value), 0.0), 1.0)
        return 0.0

    def _unknown_if_missing(self, value: Any) -> str:
        text = self._optional_unknown(value)
        return text if text != "Unknown" else "Unknown"

    def _optional_unknown(self, value: Any) -> str:
        if value is None:
            return "Unknown"
        text = str(value).strip()
        return text or "Unknown"
