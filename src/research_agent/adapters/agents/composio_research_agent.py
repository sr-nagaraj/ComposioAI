"""Composio-backed research agent placeholder."""

from research_agent.domain.input_models import AppInput
from research_agent.domain.research_models import ResearchResult
from research_agent.interfaces.research_agent_port import ResearchAgentPort


class ComposioResearchAgent(ResearchAgentPort):
    """Research adapter to be implemented when Composio integration begins."""

    async def research(self, app: AppInput) -> ResearchResult:
        raise NotImplementedError("Composio research integration is planned for Phase 3.")
