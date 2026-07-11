"""Composio-backed verification agent adapter."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from research_agent.domain.enums import EvidenceType, VerificationStatus
from research_agent.domain.research_models import Evidence, ResearchResult
from research_agent.domain.verification_models import VerificationResult
from research_agent.interfaces.verification_agent_port import VerificationAgentPort

UNKNOWN = "Unknown"
SEARCH_TOOL = "COMPOSIO_SEARCH_DUCK_DUCK_GO"
FETCH_TOOL = "COMPOSIO_SEARCH_FETCH_URL_CONTENT"
COMPOSIO_SEARCH_TOOLKIT_VERSION_ENV = "COMPOSIO_TOOLKIT_VERSION_COMPOSIO_SEARCH"
DEFAULT_COMPOSIO_SEARCH_TOOLKIT_VERSION = "20260618_00"
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
FIELD_STATUSES = {"PASS", "FAIL", "UNKNOWN"}
FieldStatus = Literal["PASS", "FAIL", "UNKNOWN"]


class VerificationEvidenceItem(BaseModel):
    """Structured evidence returned by OpenAI for a verified field."""

    url: str = Field(default=UNKNOWN)
    excerpt: str = Field(default=UNKNOWN)
    section: str = Field(default=UNKNOWN)


class VerificationFieldResults(BaseModel):
    """Per-field PASS/FAIL/UNKNOWN statuses."""

    category: FieldStatus = Field(default="UNKNOWN")
    description: FieldStatus = Field(default="UNKNOWN")
    authentication: FieldStatus = Field(default="UNKNOWN")
    api_type: FieldStatus = Field(default="UNKNOWN")
    sdk_available: FieldStatus = Field(default="UNKNOWN")
    existing_mcp: FieldStatus = Field(default="UNKNOWN")
    buildability: FieldStatus = Field(default="UNKNOWN")
    main_blocker: FieldStatus = Field(default="UNKNOWN")


class VerificationFieldConfidence(BaseModel):
    """Per-field confidence values from 0 to 1."""

    category: float = Field(default=0.0, ge=0, le=1)
    description: float = Field(default=0.0, ge=0, le=1)
    authentication: float = Field(default=0.0, ge=0, le=1)
    api_type: float = Field(default=0.0, ge=0, le=1)
    sdk_available: float = Field(default=0.0, ge=0, le=1)
    existing_mcp: float = Field(default=0.0, ge=0, le=1)
    buildability: float = Field(default=0.0, ge=0, le=1)
    main_blocker: float = Field(default=0.0, ge=0, le=1)


class VerificationMetadata(BaseModel):
    """OpenAI structured output schema for field-level verification."""

    field_results: VerificationFieldResults = Field(default_factory=VerificationFieldResults)
    field_confidence: VerificationFieldConfidence = Field(
        default_factory=VerificationFieldConfidence
    )
    discrepancies: list[str] = Field(default_factory=list)
    supporting_evidence: list[VerificationEvidenceItem] = Field(default_factory=list)


class FetchedDocumentation(BaseModel):
    """Fetched official documentation text for one evidence URL."""

    url: str
    content: str


class ComposioVerificationAgent(VerificationAgentPort):
    """Verify research results by reopening cited official documentation."""

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
        max_tool_iterations: int | None = None,
        max_tool_output_chars: int | None = None,
        max_output_tokens: int | None = None,
        max_doc_chars_per_url: int | None = None,
        max_total_doc_chars: int | None = None,
        max_fallback_search_results: int | None = None,
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
        self._max_output_tokens = max_output_tokens or int(
            os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "1200")
        )
        self._max_doc_chars_per_url = (
            max_doc_chars_per_url
            or max_tool_output_chars
            or int(os.getenv("MAX_VERIFICATION_DOC_CHARS_PER_URL", "6000"))
        )
        self._max_total_doc_chars = max_total_doc_chars or int(
            os.getenv("MAX_VERIFICATION_TOTAL_DOC_CHARS", "24000")
        )
        self._max_fallback_search_results = max_fallback_search_results or int(
            os.getenv("MAX_VERIFICATION_FALLBACK_SEARCH_RESULTS", "3")
        )
        self._min_interval_seconds = 1.0 / max(requests_per_second, 0.1)
        self._last_request_at = 0.0
        self._rate_limit_lock = asyncio.Lock()
        self._logger = logger or logging.getLogger(__name__)
        if max_tool_iterations is not None:
            self._logger.debug(
                "Ignoring max_tool_iterations because verification fetches docs deterministically"
            )

    async def verify(self, result: ResearchResult) -> VerificationResult:
        """Verify one research result and return a domain verification model."""

        if result.status.value == "failed" or not result.documentation_urls:
            return self._local_unverified_result(
                result,
                reason="Research result has no successful official documentation evidence.",
            )

        try:
            metadata = await self._with_retries(lambda: self._verify_with_composio(result))
            return self._build_result(result, metadata)
        except Exception as error:
            self._logger.exception(
                "Composio verification failed",
                extra={"app_name": result.app_name, "error_type": type(error).__name__},
            )
            return self._local_unverified_result(result, reason=f"{type(error).__name__}: {error}")

    async def _verify_with_composio(self, result: ResearchResult) -> dict[str, Any]:
        await self._respect_rate_limit()
        return await asyncio.wait_for(
            asyncio.to_thread(self._run_composio_openai_session, result),
            timeout=self._timeout_seconds,
        )

    def _run_composio_openai_session(self, result: ResearchResult) -> dict[str, Any]:
        if not self._composio_api_key:
            raise RuntimeError("COMPOSIO_API_KEY is required for Composio verification.")
        if not self._openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for metadata verification.")

        try:
            from composio import Composio
            from openai import OpenAI
        except ImportError as error:
            raise RuntimeError("Install official packages: `composio` and `openai`.") from error

        composio = Composio(api_key=self._composio_api_key)
        client = OpenAI(api_key=self._openai_api_key, max_retries=0)

        docs = self._fetch_existing_documentation(composio, result)
        if not docs:
            self._logger.warning(
                "All cited documentation URLs failed; running one fallback search",
                extra={"app_name": result.app_name},
            )
            docs = self._fallback_search_and_fetch(composio, result)

        if not docs:
            return self._unknown_metadata(
                result,
                reason="Could not fetch any cited official documentation URL.",
            )

        self._logger.info(
            "Sending fetched documentation to OpenAI",
            extra={
                "app_name": result.app_name,
                "url_count": len(docs),
                "doc_chars": sum(len(doc.content) for doc in docs),
            },
        )
        response = client.responses.parse(
            model=self._model_name,
            input=[
                {
                    "role": "user",
                    "content": self._verification_prompt(result, docs),
                }
            ],
            max_output_tokens=self._max_output_tokens,
            text_format=VerificationMetadata,
        )
        parsed = response.output_parsed
        if parsed is None:
            return self._unknown_metadata(result, reason="OpenAI did not return parsed JSON.")

        return self._normalize_verification(result, parsed.model_dump(), docs)

    def _fetch_existing_documentation(
        self,
        composio: Any,
        result: ResearchResult,
    ) -> list[FetchedDocumentation]:
        docs: list[FetchedDocumentation] = []
        for raw_url in result.documentation_urls:
            url = str(raw_url)
            try:
                fetched = self._fetch_documentation_url(composio, url)
            except Exception as error:
                self._logger.warning(
                    "Failed to fetch cited documentation URL",
                    extra={
                        "app_name": result.app_name,
                        "url": url,
                        "error_type": type(error).__name__,
                    },
                )
                continue
            if fetched is not None:
                docs.append(fetched)

        self._logger.info(
            "Fetched cited documentation",
            extra={
                "app_name": result.app_name,
                "requested_url_count": len(result.documentation_urls),
                "fetched_url_count": len(docs),
            },
        )
        return docs

    def _fetch_documentation_url(self, composio: Any, url: str) -> FetchedDocumentation | None:
        self._logger.info(
            "Fetching cited documentation URL",
            extra={"tool": FETCH_TOOL, "url": url},
        )
        response = composio.tools.execute(
            FETCH_TOOL,
            arguments={
                "urls": [url],
                "text": True,
                "max_characters": self._max_doc_chars_per_url,
            },
            user_id=self._user_id,
            version=self._composio_search_toolkit_version,
        )
        content = self._extract_document_text(response)
        if not content.strip():
            self._logger.warning("Fetched documentation was empty", extra={"url": url})
            return None

        compacted = content[: self._max_doc_chars_per_url]
        self._logger.info(
            "Fetched documentation text",
            extra={"url": url, "chars": len(compacted)},
        )
        return FetchedDocumentation(url=url, content=compacted)

    def _fallback_search_and_fetch(
        self,
        composio: Any,
        result: ResearchResult,
    ) -> list[FetchedDocumentation]:
        query = f"{result.app_name} official developer documentation API authentication SDK"
        self._logger.info(
            "Running fallback documentation search",
            extra={"app_name": result.app_name, "tool": SEARCH_TOOL, "query": query},
        )
        search_results = composio.tools.execute(
            SEARCH_TOOL,
            arguments={"query": query},
            user_id=self._user_id,
            version=self._composio_search_toolkit_version,
        )
        docs: list[FetchedDocumentation] = []
        for url in self._extract_urls(json.dumps(search_results, default=str)):
            if not self._looks_like_documentation_url(url):
                continue
            try:
                fetched = self._fetch_documentation_url(composio, url)
            except Exception as error:
                self._logger.warning(
                    "Failed to fetch fallback documentation URL",
                    extra={
                        "app_name": result.app_name,
                        "url": url,
                        "error_type": type(error).__name__,
                    },
                )
                continue
            if fetched is not None:
                docs.append(fetched)
            if len(docs) >= self._max_fallback_search_results:
                break
        return docs

    def _verification_prompt(
        self,
        result: ResearchResult,
        docs: list[FetchedDocumentation],
    ) -> str:
        original_metadata = json.dumps(
            self._original_metadata(result),
            indent=2,
            default=str,
        )
        documentation = self._format_documentation(docs)
        return f"""
You are independently verifying SaaS API research for: {result.app_name}

The code has already fetched the official documentation text. Do not search,
browse, fetch URLs, inspect Composio tools, manage connections, or ask for more
tools. Use only the documentation text below.

Compare every field independently against the documentation text:
{json.dumps(list(VERIFY_FIELDS), indent=2)}

Original research metadata:
{original_metadata}

Official documentation text:
{documentation}

Return only JSON matching this schema:
{{
  "field_results": {{
    "category": "PASS | FAIL | UNKNOWN",
    "description": "PASS | FAIL | UNKNOWN",
    "authentication": "PASS | FAIL | UNKNOWN",
    "api_type": "PASS | FAIL | UNKNOWN",
    "sdk_available": "PASS | FAIL | UNKNOWN",
    "existing_mcp": "PASS | FAIL | UNKNOWN",
    "buildability": "PASS | FAIL | UNKNOWN",
    "main_blocker": "PASS | FAIL | UNKNOWN"
  }},
  "field_confidence": {{
    "category": 0.0,
    "description": 0.0,
    "authentication": 0.0,
    "api_type": 0.0,
    "sdk_available": 0.0,
    "existing_mcp": 0.0,
    "buildability": 0.0,
    "main_blocker": 0.0
  }},
  "discrepancies": [],
  "supporting_evidence": [
    {{
      "url": "https://official.example/docs",
      "excerpt": "short quote",
      "section": "Authentication"
    }}
  ]
}}

Rules:
- PASS means the original field is directly supported by the documentation.
- FAIL means the documentation contradicts the original field.
- UNKNOWN means the documentation does not contain enough evidence for that field.
- Use UNKNOWN only after checking the provided documentation text.
- Each confidence value must be from 0 to 1.
- Add a discrepancy for every FAIL and every UNKNOWN field, with the field name and reason.
- supporting_evidence must contain short excerpts from the fetched documentation text only.
- Do not include markdown or commentary outside the JSON object.
""".strip()

    def _format_documentation(self, docs: list[FetchedDocumentation]) -> str:
        remaining_chars = self._max_total_doc_chars
        sections: list[str] = []
        for index, doc in enumerate(docs, start=1):
            if remaining_chars <= 0:
                break
            content = doc.content[:remaining_chars]
            remaining_chars -= len(content)
            sections.append(
                f"--- DOCUMENT {index} ---\nURL: {doc.url}\nCONTENT:\n{content}"
            )
        return "\n\n".join(sections)

    def _original_metadata(self, result: ResearchResult) -> dict[str, Any]:
        raw_metadata = result.raw_agent_metadata or {}
        metadata = {
            "category": result.category or raw_metadata.get("category", UNKNOWN),
            "description": result.summary or raw_metadata.get("description", UNKNOWN),
        }
        for field in VERIFY_FIELDS:
            metadata.setdefault(field, raw_metadata.get(field, UNKNOWN))
        return metadata

    async def _with_retries(self, operation: Callable[[], Any]) -> dict[str, Any]:
        delay_seconds = 2.0
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                return await operation()
            except Exception as error:
                last_error = error
                if attempt >= self._max_retries:
                    break

                self._logger.warning(
                    "Retrying Composio verification after transient failure",
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
            raise RuntimeError("Composio verification failed without an exception.")
        raise last_error

    async def _respect_rate_limit(self) -> None:
        async with self._rate_limit_lock:
            elapsed = time.monotonic() - self._last_request_at
            wait_seconds = self._min_interval_seconds - elapsed
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            self._last_request_at = time.monotonic()

    def _normalize_verification(
        self,
        result: ResearchResult,
        metadata: dict[str, Any],
        docs: list[FetchedDocumentation],
    ) -> dict[str, Any]:
        field_results = self._normalize_field_results(metadata.get("field_results"))
        field_confidence = self._normalize_field_confidence(
            metadata.get("field_confidence"),
            field_results,
        )
        confidence_score = self._calculate_confidence(field_results, field_confidence)
        supporting_evidence = self._normalize_supporting_evidence(
            metadata.get("supporting_evidence"),
            docs,
            confidence_score,
        )
        discrepancies = self._normalize_discrepancies(
            metadata.get("discrepancies"),
            field_results,
        )

        normalized = {
            "verification_status": self._status_for(field_results),
            "confidence_score": confidence_score,
            "field_results": field_results,
            "field_confidence": field_confidence,
            "discrepancies": discrepancies,
            "supporting_evidence": supporting_evidence,
        }
        self._logger.info(
            "Verification normalized",
            extra={
                "app_name": result.app_name,
                "verification_status": normalized["verification_status"].value,
                "confidence_score": confidence_score,
                "pass_count": sum(value == "PASS" for value in field_results.values()),
                "fail_count": sum(value == "FAIL" for value in field_results.values()),
                "unknown_count": sum(value == "UNKNOWN" for value in field_results.values()),
            },
        )
        return normalized

    def _normalize_field_results(self, value: Any) -> dict[str, str]:
        raw_results = value if isinstance(value, dict) else {}
        normalized: dict[str, str] = {}
        for field in VERIFY_FIELDS:
            status = str(raw_results.get(field, UNKNOWN)).strip().upper()
            normalized[field] = status if status in FIELD_STATUSES else UNKNOWN
        return normalized

    def _normalize_field_confidence(
        self,
        value: Any,
        field_results: dict[str, str],
    ) -> dict[str, float]:
        raw_confidence = value if isinstance(value, dict) else {}
        normalized: dict[str, float] = {}
        for field, status in field_results.items():
            if field in raw_confidence:
                normalized[field] = self._coerce_confidence(raw_confidence[field])
            elif status == "PASS":
                normalized[field] = 0.85
            elif status == "FAIL":
                normalized[field] = 0.2
            else:
                normalized[field] = 0.0
        return normalized

    def _normalize_supporting_evidence(
        self,
        value: Any,
        docs: list[FetchedDocumentation],
        confidence_score: float,
    ) -> list[Evidence]:
        evidence_items = value if isinstance(value, list) else []
        evidence: list[Evidence] = []
        fetched_urls = {doc.url for doc in docs}

        for item in evidence_items:
            if isinstance(item, BaseModel):
                raw_item = item.model_dump()
            elif isinstance(item, dict):
                raw_item = item
            else:
                continue

            url = str(raw_item.get("url") or "").strip()
            excerpt = str(raw_item.get("excerpt") or "").strip()
            section = str(raw_item.get("section") or "").strip()
            if url not in fetched_urls or not excerpt:
                continue
            try:
                evidence.append(
                    Evidence(
                        source_url=url,
                        source_type=EvidenceType.OFFICIAL_DOCS,
                        excerpt=self._format_excerpt(excerpt, section),
                        relevance_score=confidence_score,
                        retrieved_at=datetime.now(UTC),
                    )
                )
            except ValidationError:
                self._logger.warning("Skipping invalid verification evidence", extra={"url": url})

        if evidence:
            return evidence

        fallback_doc = docs[0]
        return [
            Evidence(
                source_url=fallback_doc.url,
                source_type=EvidenceType.OFFICIAL_DOCS,
                excerpt=self._format_excerpt(fallback_doc.content[:500], UNKNOWN),
                relevance_score=confidence_score,
                retrieved_at=datetime.now(UTC),
            )
        ]

    def _normalize_discrepancies(
        self,
        value: Any,
        field_results: dict[str, str],
    ) -> list[str]:
        discrepancies = self._normalize_string_list(value)
        fields_with_reasons = {
            item.split(":", 1)[0].strip().lower()
            for item in discrepancies
            if ":" in item
        }

        for field, status in field_results.items():
            if status == "PASS" or field in fields_with_reasons:
                continue
            if status == "FAIL":
                discrepancies.append(f"{field}: documentation contradicts the original research.")
            else:
                discrepancies.append(f"{field}: not enough documentation evidence to verify.")
        return discrepancies

    def _unknown_metadata(self, result: ResearchResult, *, reason: str) -> dict[str, Any]:
        field_results = {field: "UNKNOWN" for field in VERIFY_FIELDS}
        field_confidence = {field: 0.0 for field in VERIFY_FIELDS}
        return {
            "verification_status": VerificationStatus.UNVERIFIED,
            "confidence_score": 0.0,
            "field_results": field_results,
            "field_confidence": field_confidence,
            "discrepancies": [reason],
            "supporting_evidence": [],
        }

    def _build_result(
        self,
        research_result: ResearchResult,
        metadata: dict[str, Any],
    ) -> VerificationResult:
        try:
            return VerificationResult(
                app_name=research_result.app_name,
                research_result_ref=research_result.app_name,
                verification_status=metadata["verification_status"],
                confidence_score=metadata["confidence_score"],
                field_results=metadata["field_results"],
                field_confidence=metadata["field_confidence"],
                discrepancies=metadata["discrepancies"],
                supporting_evidence=metadata["supporting_evidence"],
                verified_at=datetime.now(UTC),
            )
        except ValidationError as error:
            return self._local_unverified_result(
                research_result,
                reason=f"VerificationResult validation failed: {error}",
            )

    def _local_unverified_result(
        self, result: ResearchResult, *, reason: str
    ) -> VerificationResult:
        return VerificationResult(
            app_name=result.app_name,
            research_result_ref=result.app_name,
            verification_status=VerificationStatus.UNVERIFIED,
            confidence_score=0.0,
            field_results={field: "UNKNOWN" for field in VERIFY_FIELDS},
            field_confidence={field: 0.0 for field in VERIFY_FIELDS},
            discrepancies=[reason],
            supporting_evidence=[],
            verified_at=datetime.now(UTC),
        )

    def _status_for(self, field_results: dict[str, str]) -> VerificationStatus:
        values = list(field_results.values())
        pass_count = values.count("PASS")
        fail_count = values.count("FAIL")
        unknown_count = values.count("UNKNOWN")

        if pass_count == len(VERIFY_FIELDS):
            return VerificationStatus.VERIFIED
        if unknown_count == len(VERIFY_FIELDS):
            return VerificationStatus.UNVERIFIED
        if fail_count > pass_count:
            return VerificationStatus.CONTRADICTED
        return VerificationStatus.PARTIALLY_VERIFIED

    def _calculate_confidence(
        self,
        field_results: dict[str, str],
        field_confidence: dict[str, float],
    ) -> float:
        if not field_results:
            return 0.0
        weighted_scores = []
        for field, status in field_results.items():
            confidence = field_confidence.get(field, 0.0)
            if status == "PASS":
                weighted_scores.append(confidence)
            elif status == "FAIL":
                weighted_scores.append(confidence * 0.25)
            else:
                weighted_scores.append(0.0)
        return round(sum(weighted_scores) / len(VERIFY_FIELDS), 2)

    def _extract_document_text(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            text_values = [
                item
                for key, item in value.items()
                if key.lower() in {"text", "content", "body", "markdown", "data"}
            ]
            if text_values:
                return "\n".join(self._extract_document_text(item) for item in text_values)
        if isinstance(value, list):
            return "\n".join(self._extract_document_text(item) for item in value)
        return json.dumps(value, default=str)

    def _extract_urls(self, text: str) -> list[str]:
        urls: list[str] = []
        for match in re.findall(r"https?://[^\s\"'<>)}\]]+", text):
            url = match.rstrip(".,;:")
            if url not in urls:
                urls.append(url)
        return urls

    def _looks_like_documentation_url(self, url: str) -> bool:
        lowered_url = url.lower()
        if "composio" in lowered_url:
            return False
        return any(
            marker in lowered_url
            for marker in ("api", "docs", "developer", "developers", "reference", "sdk")
        )

    def _format_excerpt(self, excerpt: str, section: str) -> str:
        cleaned_excerpt = " ".join(excerpt.split())
        if section and section != UNKNOWN:
            cleaned_excerpt = f"[{section}] {cleaned_excerpt}"
        return cleaned_excerpt[:1000] or "Official documentation evidence."

    def _coerce_confidence(self, value: Any) -> float:
        if isinstance(value, int | float):
            numeric_value = float(value)
            if numeric_value > 1:
                numeric_value /= 100
            return round(min(max(numeric_value, 0.0), 1.0), 2)
        return 0.0

    def _normalize_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _load_dotenv(self) -> None:
        try:
            from dotenv import load_dotenv
        except ImportError:
            return

        load_dotenv()
