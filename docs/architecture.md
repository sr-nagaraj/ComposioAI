# AI Research Agent Pipeline - Phase 1 Architecture

This project follows Clean Architecture's Dependency Rule. Domain models sit at
the center and know nothing about Composio, files, or HTML. Use cases and
analytics wrap around them. Concrete Composio/MCP-backed agents, file I/O, and
HTML rendering live at the outer edge and are reachable only through abstract
interfaces.

## Folder Structure

```text
ai-research-agent/
  config/
  data/
    input/
    output/
    checkpoints/
  src/research_agent/
    domain/
    interfaces/
    use_cases/
    analytics/
    adapters/
      agents/
      reporting/
      storage/
    infrastructure/
    cli/
  logs/
  tests/
  docs/
```

## Layer Responsibilities

`domain/` contains pure Pydantic models and enums. It has no dependency on
Composio, files, HTTP, or HTML rendering.

`interfaces/` contains ports that describe what the application needs from
research agents, verification agents, and storage.

`use_cases/` contains application business rules: research, verification,
report generation, and orchestration.

`analytics/` contains pure computation over research and verification results.

`adapters/` translates between external tools or formats and the application
core. The only package that should import Composio is `adapters/agents/`.

`infrastructure/` contains logging, retry, rate limiting, checkpointing, and
caching primitives.

`cli/` is the thin composition root.

## Data Flow

```text
apps.csv
  -> CSV reader
List[AppInput]
  -> research agent
List[ResearchResult]
  -> verification agent
List[VerificationResult]
  -> analytics engine
Analytics + List[AppSummary]
  -> HTML generator
index.html
```

Research and verification stages are sequential as stages, but each stage can
process many apps concurrently.

## Configuration Boundary

Environment-specific values and secrets belong in `.env` and `config/settings.py`.
Static, non-secret values belong in `config/constants.py`. Data-model enums
belong in `domain/enums.py`.

## Scaling Notes

The initial architecture is designed for bounded `asyncio` concurrency. For
larger runs, process apps in chunks, persist per-app checkpoints, introduce a
queue and workers when one process is no longer enough, and shard intermediate
storage when monolithic JSON files become unwieldy.
