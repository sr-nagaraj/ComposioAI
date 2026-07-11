"""Typed runtime settings loaded from environment variables."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated application settings."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["development", "production", "test"] = Field(default="development", alias="ENV")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", alias="LOG_LEVEL"
    )
    max_concurrent_requests: int = Field(default=5, alias="MAX_CONCURRENT_REQUESTS", gt=0)
    requests_per_second: int = Field(default=2, alias="REQUESTS_PER_SECOND", gt=0)
    input_path: Path = Field(default=Path("data/input/apps.csv"), alias="INPUT_PATH")
    output_dir: Path = Field(default=Path("data/output"), alias="OUTPUT_DIR")
    checkpoint_dir: Path = Field(default=Path("data/checkpoints"), alias="CHECKPOINT_DIR")
    log_dir: Path = Field(default=Path("logs"), alias="LOG_DIR")
    composio_api_key: str | None = Field(default=None, alias="COMPOSIO_API_KEY")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    model_name: str = Field(default="gpt-4.1", alias="MODEL_NAME")

    @field_validator("input_path", "output_dir", "checkpoint_dir", "log_dir")
    @classmethod
    def resolve_path(cls, value: Path) -> Path:
        return value.expanduser()


settings = Settings()
