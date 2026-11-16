"""Stan debaty (`DebateState`), wypowiedzi (`Turn`) i komendy reżysera."""

from __future__ import annotations

import operator
import uuid
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field

from debate_core.script import DebateScript

Side = Literal["dogs", "cats"]
SIDES: tuple[Side, ...] = ("dogs", "cats")
Speaker = Literal["host", "dogs", "cats"]

TurnKind = Literal[
    "intro",  # otwarcie debaty
    "block_intro",  # zapowiedź bloku
    "question",  # pytanie prowadzącego (także dodatkowe pytanie reżysera)
    "ad_vocem",
    "answer",
    "reprimand",
    "block_summary",
    "closing_statement",
    "summary",  # podsumowanie prowadzącego na koniec
]

Phase = Literal["opening", "block", "closing_statements", "closing", "done", "stopped"]

# Następny krok przebiegu. Router wybiera na jego podstawie węzeł grafu.
Step = Literal["opening", "block_intro", "question", "debater", "decide", "block_summary", "closing_statement", "closing", "done"]


def opponent(side: Side) -> Side:
    return "cats" if side == "dogs" else "dogs"


class Turn(BaseModel):
    speaker: Speaker
    kind: TurnKind
    text: str
    block_idx: int | None = None
    passed: bool = False  # ad vocem pominięte odpowiedzią PASS


def _command_id() -> str:
    return uuid.uuid4().hex[:8]


class Reprimand(BaseModel):
    type: Literal["reprimand"] = "reprimand"
    id: str = Field(default_factory=_command_id)
    target: Side
    reason: str = Field(min_length=1)


class ExtraQuestion(BaseModel):
    type: Literal["extra_question"] = "extra_question"
    id: str = Field(default_factory=_command_id)
    text: str = Field(min_length=1)
    target: Side | Literal["both"] = "both"


class Note(BaseModel):
    type: Literal["note"] = "note"
    id: str = Field(default_factory=_command_id)
    text: str = Field(min_length=1)


DirectorCommand = Annotated[Reprimand | ExtraQuestion | Note, Field(discriminator="type")]


class DebateState(TypedDict):
    script: DebateScript
    phase: Phase
    step: Step
    block_idx: int
    question_idx: int  # zwykłe pytania zadane w bieżącym bloku (bez dodatkowych)
    questions_total: int  # wszystkie pytania w debacie, steruje naprzemienną kolejnością
    current_question: str | None
    next_question: str | None  # pytanie przygotowane przez host_decide
    answer_order: list[Side]
    pending_speakers: list[Side]  # kto jeszcze odpowiada na bieżące pytanie
    debater_substep: Literal["ad_vocem", "answer"]
    resume_step: Step | None  # dokąd wrócić po dodatkowym pytaniu
    first_order: list[Side]  # kolejność odpowiedzi na pierwsze pytanie
    closing_order: list[Side]  # kto jeszcze wygłasza mowę końcową
    transcript: Annotated[list[Turn], operator.add]
    pending_director: list[Reprimand | ExtraQuestion]
    reprimands: dict[str, list[str]]
    notes: list[str]


def initial_state(script: DebateScript) -> DebateState:
    return DebateState(
        script=script,
        phase="opening",
        step="opening",
        block_idx=0,
        question_idx=0,
        questions_total=0,
        current_question=None,
        next_question=None,
        answer_order=[],
        pending_speakers=[],
        debater_substep="answer",
        resume_step=None,
        first_order=[],
        closing_order=[],
        transcript=[],
        pending_director=[],
        reprimands={"dogs": [], "cats": []},
        notes=[],
    )
