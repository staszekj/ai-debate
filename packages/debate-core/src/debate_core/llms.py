"""Fabryki modeli: prowadzący (komercyjny LLM) i debatanci (Bielik przez vLLM)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from debate_core.config import Settings, get_settings
from debate_core.state import Side


class HostDecision(BaseModel):
    """Decyzja prowadzącego po pytaniu: czy temat bloku jest wyczerpany."""

    block_exhausted: bool = Field(description="Czy temat bloku jest wyczerpany i można go podsumować")
    next_question: str | None = Field(
        None, description="Kolejne pytanie do obu drużyn (1–2 zdania), jeśli temat nie jest wyczerpany"
    )


Decider = Callable[[list[BaseMessage]], Awaitable[HostDecision]]


def make_host(settings: Settings | None = None, **kwargs: Any) -> BaseChatModel:
    """Prowadzący. Dostawcę wybiera `HOST_MODEL`, np. `anthropic:claude-haiku-5-5`."""
    s = settings or get_settings()
    if s.host_model.startswith("anthropic:") and s.host_effort:
        kwargs.setdefault("effort", s.host_effort)
    return init_chat_model(s.host_model, **kwargs)


def make_decider(host: BaseChatModel) -> Decider:
    """`host_decide` przez structured output (natywny JSON schema, bez wymuszania narzędzia)."""
    structured = host.with_structured_output(HostDecision, method="json_schema")

    async def decide(messages: list[BaseMessage]) -> HostDecision:
        result = await structured.ainvoke(messages)
        return result if isinstance(result, HostDecision) else HostDecision.model_validate(result)

    return decide


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
