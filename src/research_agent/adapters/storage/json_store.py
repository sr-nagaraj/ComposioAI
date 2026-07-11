"""JSON model storage adapter."""

import json
from pathlib import Path
from typing import TypeVar

import aiofiles
from pydantic import BaseModel

from research_agent.adapters.storage.csv_reader import CSVReader
from research_agent.domain.input_models import AppInput
from research_agent.interfaces.storage_port import StoragePort

ModelT = TypeVar("ModelT", bound=BaseModel)


class JsonStore(StoragePort):
    """Read CSV inputs and persist domain model lists as JSON."""

    def __init__(self, csv_reader: CSVReader | None = None) -> None:
        self._csv_reader = csv_reader or CSVReader()

    async def read_apps(self, path: Path) -> list[AppInput]:
        return self._csv_reader.read(path)

    async def write_models(self, path: Path, models: list[ModelT]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [model.model_dump(mode="json") for model in models]
        async with aiofiles.open(path, "w", encoding="utf-8") as file:
            await file.write(json.dumps(payload, indent=2))

    async def write_model(self, path: Path, model: BaseModel) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = model.model_dump(mode="json")
        async with aiofiles.open(path, "w", encoding="utf-8") as file:
            await file.write(json.dumps(payload, indent=2))

    async def read_models(self, path: Path, model_type: type[ModelT]) -> list[ModelT]:
        async with aiofiles.open(path, encoding="utf-8") as file:
            payload = json.loads(await file.read())
        return [model_type.model_validate(item) for item in payload]
