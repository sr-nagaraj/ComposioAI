"""Abstract verification agent contract."""

from abc import ABC, abstractmethod

from research_agent.domain.research_models import ResearchResult
from research_agent.domain.verification_models import VerificationResult


class VerificationAgentPort(ABC):
    """Port for verifying one research result."""

    @abstractmethod
    async def verify(self, result: ResearchResult) -> VerificationResult:
        """Verify a single research result."""
