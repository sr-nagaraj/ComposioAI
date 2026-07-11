"""Top-level pipeline orchestration."""

import logging
from pathlib import Path

from research_agent.adapters.reporting.html_generator import HtmlGenerator
from research_agent.analytics.engine import AnalyticsEngine
from research_agent.domain.analytics_models import Analytics
from research_agent.domain.research_models import ResearchResult
from research_agent.domain.verification_models import VerificationResult
from research_agent.interfaces.storage_port import StoragePort
from research_agent.use_cases.run_research import RunResearch
from research_agent.use_cases.run_verification import RunVerification


class PipelineOrchestrator:
    """Drive the staged research pipeline through abstract ports."""

    def __init__(
        self,
        storage: StoragePort,
        run_research: RunResearch,
        run_verification: RunVerification,
        analytics_engine: AnalyticsEngine,
        html_generator: HtmlGenerator,
        logger: logging.Logger | None = None,
    ) -> None:
        self._storage = storage
        self._run_research = run_research
        self._run_verification = run_verification
        self._analytics_engine = analytics_engine
        self._html_generator = html_generator
        self._logger = logger or logging.getLogger(__name__)

    async def run(
        self,
        input_path: Path,
        research_output_path: Path,
        verification_output_path: Path,
        analytics_output_path: Path,
        html_output_path: Path,
    ) -> tuple[list[ResearchResult], list[VerificationResult], Analytics]:
        self._logger.info("Reading CSV", extra={"input_path": str(input_path)})
        apps = await self._storage.read_apps(input_path)

        self._logger.info("Running research", extra={"app_count": len(apps)})
        research_results = await self._run_research(apps)
        await self._storage.write_models(research_output_path, research_results)
        self._logger.info(
            "Research completed",
            extra={
                "result_count": len(research_results),
                "output_path": str(research_output_path),
            },
        )

        self._logger.info("Running verification", extra={"result_count": len(research_results)})
        verification_results = await self._run_verification(research_results)
        await self._storage.write_models(verification_output_path, verification_results)
        self._logger.info(
            "Verification completed",
            extra={
                "result_count": len(verification_results),
                "output_path": str(verification_output_path),
            },
        )

        analytics = self._analytics_engine.build(research_results, verification_results)
        await self._write_analytics(analytics_output_path, analytics)
        self._logger.info("Analytics generated", extra={"output_path": str(analytics_output_path)})

        await self._html_generator.render(
            research_results=research_results,
            verification_results=verification_results,
            analytics=analytics,
            output_path=html_output_path,
        )
        self._logger.info("HTML report generated", extra={"output_path": str(html_output_path)})
        self._logger.info("Pipeline completed successfully")
        return research_results, verification_results, analytics

    async def _write_analytics(self, path: Path, analytics: Analytics) -> None:
        write_model = getattr(self._storage, "write_model", None)
        if write_model is None:
            await self._storage.write_models(path, [analytics])
            return
        await write_model(path, analytics)
