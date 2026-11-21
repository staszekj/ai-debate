"""Ustawienia z `.env.local` i zmiennych środowiskowych.

`.env.local` (poza gitem) szukany jest w bieżącym katalogu i wyżej, więc
`uv run debate ...` działa z dowolnego podkatalogu repo. Plik jest też ładowany
do `os.environ`, bo klucze dostawców (np. `ANTHROPIC_API_KEY`) czytają
bezpośrednio pakiety `langchain-*`. Zmienne ustawione w powłoce mają pierwszeństwo.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

from debate_core.expert_graph import Side

ENV_FILE = ".env.local"


def find_env_file(start: Path | None = None) -> Path | None:
    """Najbliższy `.env.local` w `start` lub katalogach nadrzędnych."""
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        candidate = d / ENV_FILE
        if candidate.is_file():
            return candidate
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # Prowadzący: dowolny model obsługiwany przez `init_chat_model` ("dostawca:model").
    host_model: str = "anthropic:claude-haiku-5-5"
    # Effort (głębokość myślenia) dla modeli Anthropic; pusty = domyślny modelu.
    host_effort: str | None = "low"

    # Debatanci: serwer zgodny z OpenAI (vLLM). DEBATER_MODEL = --served-model-name.
    debater_base_url: str = "http://127.0.0.1:8000/v1"
    debater_model: str = "bielik"
    debater_api_key: str = "EMPTY"
    debater_temperature: float = 0.7

    # Opcjonalne rozdzielenie stron na osobne serwery.
    dogs_base_url: str | None = None
    cats_base_url: str | None = None

    def base_url_for(self, side: Side) -> str:
        override = {"dogs": self.dogs_base_url, "cats": self.cats_base_url}[side]
        return override or self.debater_base_url


@lru_cache
def get_settings() -> Settings:
    env_file = find_env_file()
    if env_file:
        load_dotenv(env_file, override=False)
    return Settings()
