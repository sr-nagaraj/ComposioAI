"""Report generation use case placeholder."""

from pathlib import Path

from research_agent.domain.analytics_models import Analytics


class RunReportGeneration:
    """Coordinate final report rendering."""

    async def __call__(self, analytics: Analytics, output_path: Path) -> Path:
        raise NotImplementedError("HTML rendering adapter is planned for a later phase.")
