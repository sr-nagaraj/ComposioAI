"""Abstract storage contract for pipeline I/O."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from research_agent.domain.input_models import AppInput

ModelT = TypeVar("ModelT", bound=BaseModel)


class StoragePort(ABC):
    """Port for reading inputs and writing domain model collections."""

    @abstractmethod
    async def read_apps(self, path: Path) -> list[AppInput]:
        """Read app inputs from storage."""

    @abstractmethod
    async def write_models(self, path: Path, models: list[ModelT]) -> None:
        """Persist a collection of Pydantic models."""

    @abstractmethod
    async def read_models(self, path: Path, model_type: type[ModelT]) -> list[ModelT]:
        """Read a collection of Pydantic models."""
