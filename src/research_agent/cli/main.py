"""Command-line composition root."""

import asyncio
from pathlib import Path

import typer

from config.constants import RESEARCH_RESULTS_FILENAME, VERIFICATION_REPORT_FILENAME
from config.settings import settings
from research_agent.adapters.agents.composio_research_agent import ComposioResearchAgent
from research_agent.adapters.agents.composio_verification_agent import ComposioVerificationAgent
from research_agent.adapters.reporting.html_generator import HtmlGenerator
from research_agent.adapters.storage.json_store import JsonStore
from research_agent.analytics.engine import AnalyticsEngine
from research_agent.infrastructure.logging_setup import configure_logging
from research_agent.use_cases.pipeline_orchestrator import PipelineOrchestrator
from research_agent.use_cases.run_research import RunResearch
from research_agent.use_cases.run_verification import RunVerification

ANALYTICS_FILENAME = "analytics.json"
HTML_REPORT_FILENAME = "report.html"

app = typer.Typer(help="AI research agent pipeline.")


@app.command()
def run(
    input_path: Path = typer.Option(settings.input_path, "--input", "-i"),
    output_dir: Path = typer.Option(settings.output_dir, "--output-dir", "-o"),
) -> None:
    """Run the staged research pipeline."""

    configure_logging(settings.log_dir, settings.log_level)
    orchestrator = PipelineOrchestrator(
        storage=JsonStore(),
        run_research=RunResearch(ComposioResearchAgent(), settings.max_concurrent_requests),
        run_verification=RunVerification(
            ComposioVerificationAgent(),
            settings.max_concurrent_requests,
        ),
        analytics_engine=AnalyticsEngine(),
        html_generator=HtmlGenerator(),
    )
    asyncio.run(
        orchestrator.run(
            input_path=input_path,
            research_output_path=output_dir / RESEARCH_RESULTS_FILENAME,
            verification_output_path=output_dir / VERIFICATION_REPORT_FILENAME,
            analytics_output_path=output_dir / ANALYTICS_FILENAME,
            html_output_path=output_dir / HTML_REPORT_FILENAME,
        )
    )


if __name__ == "__main__":
    app()
