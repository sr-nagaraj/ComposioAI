"""Input data models."""

from pydantic import BaseModel, Field, HttpUrl


class AppInput(BaseModel):
    """A validated app record parsed from input CSV."""

    name: str = Field(min_length=1)
    category: str | None = None
    homepage_url: HttpUrl | None = None
    notes: str | None = None
    row_number: int = Field(ge=1)
