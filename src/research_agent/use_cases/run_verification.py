"""Verification stage use case."""

import asyncio

from research_agent.domain.research_models import ResearchResult
from research_agent.domain.verification_models import VerificationResult
from research_agent.interfaces.verification_agent_port import VerificationAgentPort


class RunVerification:
    """Run bounded concurrent verification for a batch of research results."""

    def __init__(self, agent: VerificationAgentPort, concurrency: int) -> None:
        self._agent = agent
        self._semaphore = asyncio.Semaphore(concurrency)

    async def __call__(self, results: list[ResearchResult]) -> list[VerificationResult]:
        async def verify_one(result: ResearchResult) -> VerificationResult:
            async with self._semaphore:
                return await self._agent.verify(result)

        return await asyncio.gather(*(verify_one(result) for result in results))
