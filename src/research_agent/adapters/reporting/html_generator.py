"""Jinja2 HTML report generator placeholder."""

from pathlib import Path

from research_agent.domain.analytics_models import Analytics


class HtmlGenerator:
    """Render final HTML reports from analytics data."""

    async def render(self, analytics: Analytics, output_path: Path) -> Path:
        raise NotImplementedError("HTML rendering is planned for the reporting phase.")
