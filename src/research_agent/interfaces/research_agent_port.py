"""Abstract research agent contract."""

from abc import ABC, abstractmethod

from research_agent.domain.input_models import AppInput
from research_agent.domain.research_models import ResearchResult


class ResearchAgentPort(ABC):
    """Port for researching one app."""

    @abstractmethod
    async def research(self, app: AppInput) -> ResearchResult:
        """Research a single app and return a normalized result."""
