"""Fabryki modeli: prowadzący (komercyjny LLM) i debatanci (Bielik przez vLLM)."""

from __future__ import annotations

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from debate_core.config import Settings, get_settings
from debate_core.expert_graph import Side


def make_host(settings: Settings | None = None, **kwargs: Any) -> BaseChatModel:
    """Prowadzący. Dostawcę wybiera `HOST_MODEL`, np. `anthropic:claude-haiku-5-5`."""
    s = settings or get_settings()
    if s.host_model.startswith("anthropic:") and s.host_effort:
        kwargs.setdefault("effort", s.host_effort)
    return init_chat_model(s.host_model, **kwargs)


def make_debater(side: Side, settings: Settings | None = None, **kwargs: Any) -> ChatOpenAI:
    """Debatant danej strony. Obie strony domyślnie korzystają z jednego serwera."""
    s = settings or get_settings()
    kwargs.setdefault("temperature", s.debater_temperature)
    return ChatOpenAI(
        base_url=s.base_url_for(side),
        model=s.debater_model,
        api_key=s.debater_api_key,
        **kwargs,
    )
