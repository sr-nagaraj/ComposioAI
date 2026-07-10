"""Composio-backed verification agent placeholder."""

from research_agent.domain.research_models import ResearchResult
from research_agent.domain.verification_models import VerificationResult
from research_agent.interfaces.verification_agent_port import VerificationAgentPort


class ComposioVerificationAgent(VerificationAgentPort):
    """Verification adapter to be implemented when Composio integration begins."""

    async def verify(self, result: ResearchResult) -> VerificationResult:
        raise NotImplementedError("Composio verification integration is planned for Phase 4.")
