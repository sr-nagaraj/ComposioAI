"""Composio-backed research agent adapter.

This adapter uses the official Composio Python SDK session workflow with the
documented OpenAI Responses provider tool loop. Composio SDK/OpenAI imports are
kept lazy so the project can still import without optional integration packages
installed.
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

from pydantic import ValidationError

from research_agent.domain.enums import EvidenceType, ResearchStatus
from research_agent.domain.input_models import AppInput
from research_agent.domain.research_models import Evidence, ResearchResult
from research_agent.interfaces.research_agent_port import ResearchAgentPort

UNKNOWN = "Unknown"
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


class ComposioResearchAgent(ResearchAgentPort):
    """Research official developer documentation with Composio tools."""

    def __init__(
        self,
        *,
        composio_api_key: str | None = None,
        openai_api_key: str | None = None,
        model_name: str | None = None,
        user_id: str | None = None,
        timeout_seconds: float = 120.0,
        max_retries: int = 3,
        requests_per_second: float = 1.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._composio_api_key = composio_api_key or os.getenv("COMPOSIO_API_KEY")
        self._openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self._model_name = model_name or os.getenv("MODEL_NAME", "gpt-4.1-mini")
        self._user_id = user_id or os.getenv("COMPOSIO_USER_ID", "research-agent")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._min_interval_seconds = 1.0 / max(requests_per_second, 0.1)
        self._last_request_at = 0.0
        self._rate_limit_lock = asyncio.Lock()
        self._logger = logger or logging.getLogger(__name__)

    async def research(self, app: AppInput) -> ResearchResult:
        """Research a single app and return a valid ``ResearchResult``."""

        app_name = app.name.strip()
        if not app_name:
            return self._failure_result(app_name=UNKNOWN, error=ValueError("App name is empty"))

        try:
            metadata = await self._with_retries(lambda: self._research_with_composio(app))
            return self._build_result(app_name=app_name, metadata=metadata)
        except Exception as error:
            self._logger.exception(
                "Composio research failed",
                extra={"app_name": app_name, "error_type": type(error).__name__},
            )
            return self._failure_result(app_name=app_name, error=error)

    async def _research_with_composio(self, app: AppInput) -> dict[str, Any]:
        await self._respect_rate_limit()
        return await asyncio.wait_for(
            asyncio.to_thread(self._run_composio_openai_session, app),
            timeout=self._timeout_seconds,
        )

    def _run_composio_openai_session(self, app: AppInput) -> dict[str, Any]:
        if not self._composio_api_key:
            raise RuntimeError("COMPOSIO_API_KEY is required for Composio research.")
        if not self._openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for metadata extraction.")

        try:
            from composio import Composio
            from composio_openai import OpenAIResponsesProvider
            from openai import OpenAI
        except ImportError as error:
            raise RuntimeError(
                "Install official Composio/OpenAI integration packages: "
                "`composio`, `composio_openai`, and `openai`."
            ) from error

        composio = Composio(
            api_key=self._composio_api_key,
            provider=OpenAIResponsesProvider(),
        )
        client = OpenAI(api_key=self._openai_api_key)
        session = composio.create(
            user_id=self._user_id,
            tags={"disable": ["destructiveHint"]},
            sandbox={"enable": False},
        )
        tools = session.tools()

        response = client.responses.create(
            model=self._model_name,
            tools=tools,
            input=[
                {
                    "role": "user",
                    "content": self._research_prompt(app),
                }
            ],
        )

        while True:
            tool_calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
            if not tool_calls:
                break

            self._logger.info(
                "Executing Composio tool calls",
                extra={"app_name": app.name, "tool_call_count": len(tool_calls)},
            )
            results = composio.provider.handle_tool_calls(response=response, user_id=self._user_id)
            response = client.responses.create(
                model=self._model_name,
                tools=tools,
                previous_response_id=response.id,
                input=[
                    {
                        "type": "function_call_output",
                        "call_id": tool_calls[index].call_id,
                        "output": json.dumps(result),
                    }
                    for index, result in enumerate(results)
                ],
            )

        content = self._response_text(response)
        parsed = self._parse_json_object(content)
        return self._normalize_metadata(parsed)

    async def _with_retries(self, operation: Callable[[], Any]) -> dict[str, Any]:
        delay_seconds = 1.0
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                return await operation()
            except Exception as error:
                last_error = error
                if attempt >= self._max_retries:
                    break

                self._logger.warning(
                    "Retrying Composio research",
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
            raise RuntimeError("Composio research failed without an exception.")
        raise last_error

    async def _respect_rate_limit(self) -> None:
        async with self._rate_limit_lock:
            elapsed = time.monotonic() - self._last_request_at
            wait_seconds = self._min_interval_seconds - elapsed
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            self._last_request_at = time.monotonic()

    def _research_prompt(self, app: AppInput) -> str:
        seed_context = []
        if app.category:
            seed_context.append(f"CSV category hint: {app.category}")
        if app.homepage_url:
            seed_context.append(f"CSV homepage hint: {app.homepage_url}")
        if app.notes:
            seed_context.append(f"CSV notes: {app.notes}")

        hints = "\n".join(seed_context) if seed_context else "No CSV hints were provided."
        return f"""
You are researching SaaS developer documentation for: {app.name}

Use Composio tools to discover and read official developer documentation only.
Do not use third-party blogs, summaries, or guessed URLs as evidence.
If official documentation cannot be found or a field is not explicitly supported
by evidence, return "Unknown" for that field.

Context:
{hints}

Extract these fields:
- category
- description: one sentence only
- authentication
- api_type
- sdk_available
- existing_mcp
- buildability
- main_blocker
- evidence_urls: official documentation URLs used as evidence

Return only a JSON object with exactly these keys:
{{
  "category": "Unknown",
  "description": "Unknown",
  "authentication": "Unknown",
  "api_type": "Unknown",
  "sdk_available": "Unknown",
  "existing_mcp": "Unknown",
  "buildability": "Unknown",
  "main_blocker": "Unknown",
  "evidence_urls": []
}}

Rules:
- Every non-Unknown field must be supported by at least one evidence URL.
- evidence_urls must contain only official developer documentation URLs.
- Do not include markdown, commentary, or citations outside the JSON object.
""".strip()

    def _response_text(self, response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        parts: list[str] = []
        for item in getattr(response, "output", []):
            if getattr(item, "type", None) != "message":
                continue
            for block in getattr(item, "content", []):
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    parts.append(text)
                elif isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
        return "\n".join(parts)

    def _parse_json_object(self, content: str) -> dict[str, Any]:
        if not content.strip():
            return {}

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, flags=re.DOTALL)
            if not match:
                self._logger.warning("Model response did not contain a JSON object")
                return {}
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                self._logger.warning("Model response JSON could not be decoded")
                return {}

        if not isinstance(parsed, dict):
            self._logger.warning("Model response JSON was not an object")
            return {}
        return parsed

    def _normalize_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for field in RESEARCH_FIELDS:
            if field == "evidence_urls":
                normalized[field] = self._normalize_urls(metadata.get(field))
            else:
                normalized[field] = self._unknown_if_missing(metadata.get(field))

        normalized["confidence_score"] = self._calculate_confidence(normalized)
        return normalized

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
            if not url.startswith(("https://", "http://")):
                continue
            if url in seen:
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
