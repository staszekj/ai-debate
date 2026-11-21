"""`DebateScript`: schemat debaty ustalany przez reżysera, plus gotowe presety."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

PRESETS_PACKAGE = "debate_core.presets"


class Block(BaseModel):
    topic: str = Field(min_length=1, description="Temat bloku, np. „Wpływ na mieszkańców”")
    guidance: str | None = Field(None, description="Opcjonalne wskazówki dla prowadzącego")
    questions_target: int = Field(5, ge=1, description="Docelowa liczba pytań („około 5”)")
    questions_min: int = Field(4, ge=1)
    questions_max: int = Field(6, ge=1)

    @model_validator(mode="after")
    def _check_range(self) -> Block:
        if not self.questions_min <= self.questions_target <= self.questions_max:
            raise ValueError("wymagane questions_min <= questions_target <= questions_max")
        return self


class ClosingStatement(BaseModel):
    enabled: bool = True
    words: int = Field(100, ge=20, description="Długość mowy końcowej („około N słów”)")


class Positions(BaseModel):
    dogs: str
    cats: str

    @field_validator("dogs", "cats")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("stanowisko nie może być puste")
        return value


class DebateScript(BaseModel):
    title: str = Field(min_length=1)
    positions: Positions
    blocks: list[Block] = Field(min_length=1)
    closing_statement: ClosingStatement = ClosingStatement()
    host_summary: bool = Field(True, description="Podsumowanie prowadzącego na koniec (bez werdyktu)")

    @model_validator(mode="before")
    @classmethod
    def _reject_removed_ad_vocem(cls, data: Any) -> Any:
        if isinstance(data, dict) and "ad_vocem" in data:
            raise ValueError("pole ad_vocem zostało usunięte; usuń je ze schematu debaty")
        return data


def list_presets() -> list[str]:
    files = resources.files(PRESETS_PACKAGE).iterdir()
    return sorted(f.name.removesuffix(".json") for f in files if f.name.endswith(".json"))


def load_preset(preset_id: str) -> DebateScript:
    if preset_id not in list_presets():
        raise KeyError(f"nieznany preset {preset_id!r}, dostępne: {list_presets()}")
    text = resources.files(PRESETS_PACKAGE).joinpath(f"{preset_id}.json").read_text(encoding="utf-8")
    return DebateScript.model_validate(json.loads(text))
