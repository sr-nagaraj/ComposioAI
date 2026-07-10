"""Research stage use case."""

import asyncio

from research_agent.domain.input_models import AppInput
from research_agent.domain.research_models import ResearchResult
from research_agent.interfaces.research_agent_port import ResearchAgentPort


class RunResearch:
    """Run bounded concurrent research for a batch of apps."""

    def __init__(self, agent: ResearchAgentPort, concurrency: int) -> None:
        self._agent = agent
        self._semaphore = asyncio.Semaphore(concurrency)

    async def __call__(self, apps: list[AppInput]) -> list[ResearchResult]:
        async def research_one(app: AppInput) -> ResearchResult:
            async with self._semaphore:
                return await self._agent.research(app)

        return await asyncio.gather(*(research_one(app) for app in apps))
