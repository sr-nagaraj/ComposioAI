"""Composio-backed research agent adapter using OpenAI.

The adapter preserves the existing architecture and port contract. Composio is
used for public documentation search/fetch, and OpenAI performs structured JSON
metadata extraction from the retrieved official documentation text.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError

from research_agent.domain.enums import EvidenceType, ResearchStatus
from research_agent.domain.input_models import AppInput
from research_agent.domain.research_models import Evidence, ResearchResult
from research_agent.interfaces.research_agent_port import ResearchAgentPort

UNKNOWN = "Unknown"
SEARCH_TOOL = "COMPOSIO_SEARCH_DUCK_DUCK_GO"
FETCH_TOOL = "COMPOSIO_SEARCH_FETCH_URL_CONTENT"
COMPOSIO_SEARCH_TOOLKIT_VERSION_ENV = "COMPOSIO_TOOLKIT_VERSION_COMPOSIO_SEARCH"
DEFAULT_COMPOSIO_SEARCH_TOOLKIT_VERSION = "20260618_00"
RESEARCH_FIELDS = (
    "category",
    "description",
    "authentication",
    "api_type",
    "sdk_available",
    "existing_mcp",
    "buildability",
    "main_blocker",
    "evidence_urls",
)


class ResearchMetadata(BaseModel):
    """OpenAI structured output schema for research metadata."""

    category: str = Field(default=UNKNOWN)
    description: str = Field(default=UNKNOWN)
    authentication: str = Field(default=UNKNOWN)
    api_type: str = Field(default=UNKNOWN)
    sdk_available: str = Field(default=UNKNOWN)
    existing_mcp: str = Field(default=UNKNOWN)
    buildability: str = Field(default=UNKNOWN)
    main_blocker: str = Field(default=UNKNOWN)
    evidence_urls: list[str] = Field(default_factory=list)


class ComposioResearchAgent(ResearchAgentPort):
    """Research official developer documentation with Composio and OpenAI."""

    def __init__(
        self,
        *,
        composio_api_key: str | None = None,
        openai_api_key: str | None = None,
        model_name: str | None = None,
        user_id: str | None = None,
        timeout_seconds: float = 120.0,
        max_retries: int = 1,
        requests_per_second: float = 1.0,
        max_search_results: int | None = None,
        max_doc_chars: int | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._load_dotenv()
        self._composio_api_key = composio_api_key or os.getenv("COMPOSIO_API_KEY")
        self._openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self._model_name = model_name or os.getenv("MODEL_NAME", "gpt-4.1")
        self._user_id = user_id or os.getenv("COMPOSIO_USER_ID", "research-agent")
        self._composio_search_toolkit_version = os.getenv(
            COMPOSIO_SEARCH_TOOLKIT_VERSION_ENV,
            DEFAULT_COMPOSIO_SEARCH_TOOLKIT_VERSION,
        )
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._max_search_results = max_search_results or int(os.getenv("MAX_SEARCH_RESULTS", "5"))
        self._max_doc_chars = max_doc_chars or int(os.getenv("MAX_DOC_CHARS", "6000"))
        self._min_interval_seconds = 1.0 / max(requests_per_second, 0.1)
        self._last_request_at = 0.0
        self._rate_limit_lock = asyncio.Lock()
        self._logger = logger or logging.getLogger(__name__)

    async def research(self, app: AppInput) -> ResearchResult:
        """Research a single app and return a valid ``ResearchResult``."""

        app_name = app.name.strip()
        if not app_name:
            return self._failure_result(app_name=UNKNOWN, error=ValueError("App name is empty"))

        self._logger.info("Searching docs", extra={"app_name": app_name})
        try:
            metadata = await self._with_retries(
                lambda: self._research_with_composio_and_openai(app)
            )
            self._logger.info("Finished", extra={"app_name": app_name})
            return self._build_result(app_name=app_name, metadata=metadata)
        except Exception as error:
            self._logger.exception(
                "Composio/OpenAI research failed",
                extra={"app_name": app_name, "error_type": type(error).__name__},
            )
            return self._failure_result(app_name=app_name, error=error)

    async def _research_with_composio_and_openai(self, app: AppInput) -> dict[str, Any]:
        await self._respect_rate_limit()
        return await asyncio.wait_for(
            asyncio.to_thread(self._run_research, app),
            timeout=self._timeout_seconds,
        )

    def _run_research(self, app: AppInput) -> dict[str, Any]:
        if not self._composio_api_key:
            raise RuntimeError("COMPOSIO_API_KEY is required for Composio research.")
        if not self._openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI extraction.")

        try:
            from composio import Composio
            from openai import OpenAI
        except ImportError as error:
            raise RuntimeError("Install official packages: `composio` and `openai`.") from error

        composio = Composio(api_key=self._composio_api_key)
        client = OpenAI(api_key=self._openai_api_key, max_retries=0)

        search_results = self._search_official_docs(composio, app)
        evidence_urls = self._select_official_urls(search_results, app)
        if not evidence_urls:
            self._logger.warning("No official documentation found", extra={"app_name": app.name})
            return self._unknown_metadata()

        self._logger.info(
            "Found docs",
            extra={"app_name": app.name, "evidence_urls": evidence_urls},
        )
        docs_text = self._fetch_documentation(composio, evidence_urls)
        if not docs_text.strip():
            self._logger.warning(
                "Official documentation could not be read",
                extra={"app_name": app.name},
            )
            return self._unknown_metadata(evidence_urls=evidence_urls)

        self._logger.info("Extracting metadata", extra={"app_name": app.name})
        metadata = self._extract_with_openai(client, app, evidence_urls, docs_text)
        self._logger.info("JSON generated", extra={"app_name": app.name})
        return metadata

    def _search_official_docs(self, composio: Any, app: AppInput) -> Any:
        query = self._search_query(app)
        return composio.tools.execute(
            SEARCH_TOOL,
            arguments={"query": query},
            user_id=self._user_id,
            version=self._composio_search_toolkit_version,
        )

    def _fetch_documentation(self, composio: Any, evidence_urls: list[str]) -> str:
        self._logger.info("Opening docs", extra={"evidence_urls": evidence_urls})
        response = composio.tools.execute(
            FETCH_TOOL,
            arguments={
                "urls": evidence_urls[: self._max_search_results],
                "text": True,
                "max_characters": self._max_doc_chars,
            },
            user_id=self._user_id,
            version=self._composio_search_toolkit_version,
        )
        return self._compact_text(response)

    def _extract_with_openai(
        self,
        client: Any,
        app: AppInput,
        evidence_urls: list[str],
        docs_text: str,
    ) -> dict[str, Any]:
        response = client.responses.parse(
            model=self._model_name,
            input=[
                {
                    "role": "user",
                    "content": self._openai_prompt(app, evidence_urls, docs_text),
                }
            ],
            text_format=ResearchMetadata,
        )
        parsed = response.output_parsed
        if parsed is None:
            return self._unknown_metadata(evidence_urls=evidence_urls)
        metadata = parsed.model_dump()
        metadata.setdefault("evidence_urls", evidence_urls)
        return self._normalize_metadata(metadata)

    async def _with_retries(self, operation: Callable[[], Any]) -> dict[str, Any]:
        delay_seconds = 8.0
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                return await operation()
            except Exception as error:
                last_error = error
                if attempt >= self._max_retries:
                    break

                self._logger.warning(
                    "Retrying research after transient failure",
                    extra={
                        "attempt": attempt,
                        "max_retries": self._max_retries,
                        "delay_seconds": delay_seconds,
                        "error_type": type(error).__name__,
                    },
                )
                await asyncio.sleep(delay_seconds)
                delay_seconds *= 2

        if last_error is None:
            raise RuntimeError("Research failed without an exception.")
        raise last_error

    async def _respect_rate_limit(self) -> None:
        async with self._rate_limit_lock:
            elapsed = time.monotonic() - self._last_request_at
            wait_seconds = self._min_interval_seconds - elapsed
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            self._last_request_at = time.monotonic()

    def _search_query(self, app: AppInput) -> str:
        homepage = f" {app.homepage_url}" if app.homepage_url else ""
        return (
            f"{app.name}{homepage} official developer documentation API authentication "
            "SDK REST GraphQL"
        )

    def _select_official_urls(self, search_results: Any, app: AppInput) -> list[str]:
        text = json.dumps(search_results, default=str)
        urls = self._extract_urls(text)
        official_hosts = self._official_host_hints(app)
        selected: list[str] = []

        for url in urls:
            parsed = urlparse(url)
            host = parsed.netloc.lower()
            path = parsed.path.lower()
            is_docs_path = any(
                marker in path for marker in ("api", "docs", "developer", "reference", "sdk")
            )
            is_docs_host = host.startswith(("api.", "developer.", "developers."))
            is_official_host = any(host.endswith(hint) for hint in official_hosts)
            if is_official_host and (is_docs_path or is_docs_host) and url not in selected:
                selected.append(url)
            if len(selected) >= self._max_search_results:
                break

        return selected

    def _official_host_hints(self, app: AppInput) -> list[str]:
        hints: list[str] = []
        if app.homepage_url:
            host = urlparse(str(app.homepage_url)).netloc.lower().removeprefix("www.")
            if host:
                hints.append(host)

        normalized_name = re.sub(r"[^a-z0-9]", "", app.name.lower())
        if normalized_name:
            hints.extend(
                [
                    f"{normalized_name}.com",
                    f"api.{normalized_name}.com",
                    f"developer.{normalized_name}.com",
                    f"developers.{normalized_name}.com",
                ]
            )
        return hints

    def _extract_urls(self, text: str) -> list[str]:
        urls: list[str] = []
        for match in re.findall(r"https?://[^\s\"'<>)}\]]+", text):
            url = match.rstrip(".,;:")
            if url not in urls:
                urls.append(url)
        return urls

    def _openai_prompt(self, app: AppInput, evidence_urls: list[str], docs_text: str) -> str:
        return f"""
You are extracting SaaS API metadata for: {app.name}

Use only the official documentation excerpts below.
Never guess. If a field is not explicitly supported by the documentation, use "Unknown".
Return only JSON that matches the requested schema.

Evidence URLs:
{json.dumps(evidence_urls, indent=2)}

Official documentation excerpts:
{docs_text[: self._max_doc_chars]}

Extract:
- category
- one-sentence description
- authentication
- api_type
- sdk_available
- existing_mcp
- buildability
- main_blocker
- evidence_urls
""".strip()

    def _compact_text(self, value: Any) -> str:
        serialized = json.dumps(value, default=str)
        if len(serialized) <= self._max_doc_chars:
            return serialized
        return serialized[: self._max_doc_chars]

    def _normalize_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for field in RESEARCH_FIELDS:
            if field == "evidence_urls":
                normalized[field] = self._normalize_urls(metadata.get(field))
            else:
                normalized[field] = self._unknown_if_missing(metadata.get(field))

        normalized["confidence_score"] = self._calculate_confidence(normalized)
        return normalized

    def _unknown_metadata(self, *, evidence_urls: list[str] | None = None) -> dict[str, Any]:
        metadata = {
            "category": UNKNOWN,
            "description": UNKNOWN,
            "authentication": UNKNOWN,
            "api_type": UNKNOWN,
            "sdk_available": UNKNOWN,
            "existing_mcp": UNKNOWN,
            "buildability": UNKNOWN,
            "main_blocker": UNKNOWN,
            "evidence_urls": evidence_urls or [],
        }
        metadata["confidence_score"] = self._calculate_confidence(metadata)
        return metadata

    def _build_result(self, *, app_name: str, metadata: dict[str, Any]) -> ResearchResult:
        evidence_urls = metadata.get("evidence_urls", [])
        evidence = self._build_evidence(evidence_urls, metadata["confidence_score"])
        status = self._status_for(metadata)

        try:
            return ResearchResult(
                app_name=app_name,
                status=status,
                summary=metadata["description"],
                category=metadata["category"],
                documentation_urls=evidence_urls,
                evidence=evidence,
                confidence_score=metadata["confidence_score"],
                researched_at=datetime.now(UTC),
                raw_agent_metadata=metadata,
            )
        except ValidationError as error:
            return self._failure_result(app_name=app_name, error=error, metadata=metadata)

    def _build_evidence(self, urls: list[str], confidence_score: float) -> list[Evidence]:
        evidence: list[Evidence] = []
        for url in urls:
            try:
                evidence.append(
                    Evidence(
                        source_url=url,
                        source_type=EvidenceType.OFFICIAL_DOCS,
                        excerpt="Official developer documentation evidence URL.",
                        relevance_score=confidence_score,
                        retrieved_at=datetime.now(UTC),
                    )
                )
            except ValidationError:
                self._logger.warning("Skipping invalid evidence URL", extra={"url": url})
        return evidence

    def _status_for(self, metadata: dict[str, Any]) -> ResearchStatus:
        if not metadata.get("evidence_urls"):
            return ResearchStatus.FAILED

        unknown_count = sum(
            1
            for field in RESEARCH_FIELDS
            if field != "evidence_urls" and metadata.get(field) == UNKNOWN
        )
        if unknown_count == 0:
            return ResearchStatus.SUCCESS
        return ResearchStatus.PARTIAL

    def _failure_result(
        self,
        *,
        app_name: str,
        error: Exception,
        metadata: dict[str, Any] | None = None,
    ) -> ResearchResult:
        return ResearchResult(
            app_name=app_name,
            status=ResearchStatus.FAILED,
            summary=UNKNOWN,
            category=UNKNOWN,
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

    def _normalize_urls(self, value: Any) -> list[str]:
        raw_urls = value if isinstance(value, list) else []
        urls: list[str] = []
        seen: set[str] = set()

        for raw_url in raw_urls:
            if not isinstance(raw_url, str):
                continue
            url = raw_url.strip()
            if not url.startswith(("https://", "http://")) or url in seen:
                continue
            seen.add(url)
            urls.append(url)
        return urls

    def _calculate_confidence(self, metadata: dict[str, Any]) -> float:
        evidence_count = len(metadata.get("evidence_urls", []))
        if evidence_count == 0:
            return 0.0

        known_fields = sum(
            1
            for field in RESEARCH_FIELDS
            if field != "evidence_urls" and metadata.get(field) != UNKNOWN
        )
        total_fields = len(RESEARCH_FIELDS) - 1
        field_score = known_fields / total_fields
        evidence_score = min(evidence_count / 3, 1.0)
        return round((field_score * 0.7) + (evidence_score * 0.3), 2)

    def _unknown_if_missing(self, value: Any) -> str:
        if value is None:
            return UNKNOWN
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, list):
            text = ", ".join(str(item).strip() for item in value if str(item).strip())
        else:
            text = str(value).strip()
        return text or UNKNOWN

    def _load_dotenv(self) -> None:
        try:
            from dotenv import load_dotenv
        except ImportError:
            return

        load_dotenv()
