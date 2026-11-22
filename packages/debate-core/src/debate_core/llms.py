"""Factory functions for the coordinator and the two experts."""

from __future__ import annotations

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from debate_core.config import Settings, get_settings
from debate_core.graph import Side


def make_brain(settings: Settings | None = None, **kwargs: Any) -> BaseChatModel:
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
        model=s.model_for(side),
        api_key=s.debater_api_key,
        **kwargs,
    )
