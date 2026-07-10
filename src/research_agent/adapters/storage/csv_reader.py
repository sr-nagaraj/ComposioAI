"""CSV input reader."""

from pathlib import Path

import pandas as pd

from research_agent.domain.input_models import AppInput


class CSVReader:
    """Read app inputs from CSV into domain models."""

    def read(self, path: Path) -> list[AppInput]:
        dataframe = pd.read_csv(path)
        apps: list[AppInput] = []
        for index, row in dataframe.iterrows():
            apps.append(
                AppInput(
                    name=str(row["name"]).strip(),
                    category=self._optional_string(row.get("category")),
                    homepage_url=self._optional_string(row.get("homepage_url")),
                    notes=self._optional_string(row.get("notes")),
                    row_number=index + 2,
                )
            )
        return apps

    def _optional_string(self, value: object) -> str | None:
        if pd.isna(value):
            return None
        text = str(value).strip()
        return text or None
