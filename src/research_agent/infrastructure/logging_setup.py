"""Logging configuration."""

import logging
from pathlib import Path


def configure_logging(log_dir: Path, log_level: str) -> None:
    """Configure baseline application logging."""

    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "app.log", encoding="utf-8"),
        ],
    )
