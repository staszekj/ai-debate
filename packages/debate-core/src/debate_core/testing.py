"""Fake modele do testów (debate-core i debate-api): odpowiedź wyliczana z treści promptu."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from debate_core.director import DirectorChannel
from debate_core.graph import DebateDeps
from debate_core.llms import HostDecision

Responder = Callable[[list[BaseMessage]], str]


class ScriptedChatModel(GenericFakeChatModel):
    """`GenericFakeChatModel`, którego odpowiedź zależy od wiadomości (i który zapisuje wywołania)."""

    messages: Any = iter(())  # nieużywane; odpowiedź liczy `respond`
    respond: Responder
    delay: float = 0.0  # sekundy na wywołanie (testy API potrzebują trwającej debaty)
    _calls: list[list[BaseMessage]] = PrivateAttr(default_factory=list)

    @property
    def calls(self) -> list[list[BaseMessage]]:
        return self._calls

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        self._calls.append(list(messages))
        if self.delay:
            time.sleep(self.delay)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.respond(messages)))])


def last_text(messages: list[BaseMessage]) -> str:
    return str(messages[-1].content)


def default_host(messages: list[BaseMessage]) -> str:
    task = last_text(messages)
    if "Zadaj" in task:
        return "Jakie jest wasze zdanie?"
    return "Kwestia prowadzącego."


def default_debater(messages: list[BaseMessage]) -> str:
    if "PASS" in last_text(messages):
        return "Krótkie ad vocem."
    return "Nasz argument."


class Decider:
    """Fake host_decide: zawsze ta sama decyzja, zapisuje wywołania."""

    def __init__(self, exhausted: bool, next_question: str | None = "Następne pytanie?") -> None:
        self.exhausted = exhausted
        self.next_question = next_question
        self.calls: list[list[BaseMessage]] = []

    async def __call__(self, messages: list[BaseMessage]) -> HostDecision:
        self.calls.append(messages)
        return HostDecision(block_exhausted=self.exhausted, next_question=None if self.exhausted else self.next_question)


def make_deps(
    host: Responder = default_host,
    debater: Responder = default_debater,
    decider: Decider | None = None,
    director: DirectorChannel | None = None,
    delay: float = 0.0,
) -> DebateDeps:
    return DebateDeps(
        host=ScriptedChatModel(respond=host, delay=delay),
        decide=decider or Decider(exhausted=True),
        debaters={side: ScriptedChatModel(respond=debater, delay=delay) for side in ("dogs", "cats")},
        director=director or DirectorChannel(),
    )
