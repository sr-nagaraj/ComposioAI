"""Top-level pipeline orchestration."""

from pathlib import Path

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
    ) -> None:
        self._storage = storage
        self._run_research = run_research
        self._run_verification = run_verification

    async def run(
        self,
        input_path: Path,
        research_output_path: Path,
        verification_output_path: Path,
    ) -> tuple[list[ResearchResult], list[VerificationResult]]:
        apps = await self._storage.read_apps(input_path)
        research_results = await self._run_research(apps)
        await self._storage.write_models(research_output_path, research_results)
        verification_results = await self._run_verification(research_results)
        await self._storage.write_models(verification_output_path, verification_results)
        return research_results, verification_results
