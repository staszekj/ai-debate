"""Graf debaty (LangGraph): węzły wypowiedzi, `director_gate` i router.

Strukturą (fazy, bloki, liczniki, kolejność) steruje kod. LLM-y dostarczają tylko
treść wypowiedzi i decyzję „temat wyczerpany”. Każdy węzeł wraca do
`director_gate`, a router wybiera następny węzeł na podstawie `step`, liczników,
schematu i oczekujących interwencji reżysera.

Zdarzenia dla UI / CLI idą przez `get_stream_writer()` (stream_mode="custom"):
`turn_start`, `token`, `turn_end`, `phase`, `director_ack`, `decision`, `status`.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from debate_core import prompts
from debate_core.director import DirectorChannel
from debate_core.llms import Decider, HostDecision
from debate_core.state import (
    DebateState,
    ExtraQuestion,
    Note,
    Reprimand,
    Side,
    Speaker,
    Step,
    Turn,
    TurnKind,
)

# Limity długości (tokeny). Prowadzący z adaptacyjnym myśleniem: zapas na thinking.
HOST_MAX_TOKENS = 2000
DEBATER_MAX_TOKENS = {"answer": 500, "closing_statement": 600}
RECURSION_LIMIT = 2000


@dataclass
class DebateDeps:
    host: BaseChatModel
    decide: Decider
    debaters: dict[Side, BaseChatModel]
    director: DirectorChannel


# --- pomocnicze ------------------------------------------------------------


def _emit(event: dict[str, Any]) -> None:
    get_stream_writer()(event)


def _model_start(speaker: Speaker, step: str, messages: list[BaseMessage], *, decision: bool = False) -> str:
    call_id = uuid.uuid4().hex
    event: dict[str, Any] = {
        "type": "model_start",
        "id": call_id,
        "model": speaker,
        "step": step,
        "messages": [message.model_dump(mode="json") for message in messages],
    }
    if decision:
        event["response_schema"] = HostDecision.model_json_schema()
    _emit(event)
    return call_id


def _model_end(call_id: str, speaker: Speaker, status: str, *, retain: bool = False) -> None:
    _emit({"type": "model_end", "id": call_id, "model": speaker, "status": status, "retain": retain})


async def _say(
    model: BaseChatModel, messages: list[BaseMessage], speaker: Speaker, kind: TurnKind, block_idx: int | None
) -> str:
    """Generuje wypowiedź ze streamingiem tokenów do UI."""
    _emit({"type": "turn_start", "speaker": speaker, "kind": kind, "block_idx": block_idx})
    parts: list[str] = []
    call_id = _model_start(speaker, kind, messages)
    try:
        async for chunk in model.astream(messages):
            raw = chunk.model_dump(mode="json", include={"content", "additional_kwargs", "tool_call_chunks"})
            _emit({"type": "model_chunk", "id": call_id, "model": speaker, "chunk": raw})
            text = chunk.text if parts else chunk.text.lstrip()
            if text:
                parts.append(text)
                _emit({"type": "token", "text": text})
    except asyncio.CancelledError:
        _model_end(call_id, speaker, "cancelled")
        raise
    except Exception:
        _model_end(call_id, speaker, "error")
        raise
    _model_end(call_id, speaker, "done")
    return "".join(parts).strip()


def _turn(speaker: Speaker, kind: TurnKind, text: str, block_idx: int | None) -> Turn:
    turn = Turn(speaker=speaker, kind=kind, text=text, block_idx=block_idx)
    _emit({"type": "turn_end", **turn.model_dump()})
    return turn


def _block_idx(state: DebateState) -> int | None:
    return state["block_idx"] if state["phase"] == "block" else None


def _answer_order(questions_total: int) -> list[Side]:
    return ["dogs", "cats"] if questions_total % 2 == 0 else ["cats", "dogs"]


def _phase(phase: str) -> dict[str, Any]:
    _emit({"type": "phase", "phase": phase})
    return {"phase": phase}


def _after_blocks(state: DebateState) -> dict[str, Any]:
    script = state["script"]
    if script.closing_statement.enabled:
        return {**_phase("closing_statements"), "step": "closing_statement", "closing_order": _closing_order(state)}
    if script.host_summary:
        return {**_phase("closing"), "step": "closing"}
    return {**_phase("done"), "step": "done"}


def _closing_order(state: DebateState) -> list[Side]:
    """Mowy końcowe w kolejności odwrotnej niż odpowiedzi na pierwsze pytanie."""
    return list(reversed(state["first_order"] or ["dogs", "cats"]))


def _start_question(state: DebateState, text: str, targets: list[Side]) -> dict[str, Any]:
    """Wspólne dla zwykłego i dodatkowego pytania: ustawia kolejkę odpowiadających."""
    order = [s for s in _answer_order(state["questions_total"]) if s in targets]
    return {
        "current_question": text,
        "answer_order": order,
        "pending_speakers": order,
        "questions_total": state["questions_total"] + 1,
        "first_order": state["first_order"] or order,
        "step": "debater",
    }


# --- graf ------------------------------------------------------------------


def build_graph(deps: DebateDeps, checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    host, decide, debaters, director = deps.host, deps.decide, deps.debaters, deps.director
    host_llm = host.bind(max_tokens=HOST_MAX_TOKENS)

    async def host_say(state: DebateState, kind: TurnKind, instruction: str) -> Turn:
        block_idx = _block_idx(state)
        text = await _say(host_llm, prompts.host_messages(state, instruction), "host", kind, block_idx)
        return _turn("host", kind, text, block_idx)

    async def debater_say(state: DebateState, side: Side, kind: TurnKind, instruction: str) -> tuple[str, int | None]:
        block_idx = _block_idx(state)
        model = debaters[side].bind(max_tokens=DEBATER_MAX_TOKENS[kind])
        messages = prompts.build_debater_context(state, side, instruction)
        text = await _say(model, messages, side, kind, block_idx)
        return prompts.trim_incomplete(text), block_idx

    # --- bramka reżysera -----------------------------------------------------

    async def director_gate(state: DebateState) -> dict[str, Any]:
        if director.paused:
            _emit({"type": "status", "status": "paused"})
        commands, stopped = await director.checkpoint()
        if stopped:
            _emit({"type": "status", "status": "stopped"})
            return {**_phase("stopped"), "step": "done"}
        if not commands:
            return {}
        notes, pending = list(state["notes"]), list(state["pending_director"])
        for cmd in commands:
            if isinstance(cmd, Note):
                notes.append(cmd.text)
                _emit({"type": "director_ack", "id": cmd.id, "status": "done"})
            else:
                pending.append(cmd)
                _emit({"type": "director_ack", "id": cmd.id, "status": "pending"})
        return {"notes": notes, "pending_director": pending}

    def route(state: DebateState) -> str:
        step: Step = state["step"]
        if step == "done":
            return END
        pending = state["pending_director"]
        if any(isinstance(c, Reprimand) for c in pending):
            return "host_reprimand"
        # Dodatkowe pytanie wchodzi jako następne, ale nie przerywa wymiany odpowiedzi.
        at_question_point = step in ("question", "block_summary") or (
            step == "closing_statement" and len(state["closing_order"]) == 2
        )
        if at_question_point and any(isinstance(c, ExtraQuestion) for c in pending):
            return "host_extra_question"
        if step == "debater":
            return "debater_answer"
        return {
            "opening": "host_opening",
            "block_intro": "host_block_intro",
            "question": "host_question",
            "decide": "host_decide",
            "block_summary": "host_block_summary",
            "closing_statement": "debater_closing",
            "closing": "host_closing",
        }[step]

    # --- prowadzący ----------------------------------------------------------

    async def host_opening(state: DebateState) -> dict[str, Any]:
        turn = await host_say(state, "intro", prompts.host_opening(state["script"]))
        return {"transcript": [turn], **_phase("block"), "step": "block_intro", "block_idx": 0}

    async def host_block_intro(state: DebateState) -> dict[str, Any]:
        turn = await host_say(state, "block_intro", prompts.host_block_intro(state["script"], state["block_idx"]))
        return {"transcript": [turn], "step": "question", "question_idx": 0, "next_question": None}

    async def host_question(state: DebateState) -> dict[str, Any]:
        block_idx = state["block_idx"]
        if state["next_question"]:
            # Pytanie przygotowane przez host_decide: wypowiadamy je bez kolejnego wywołania LLM.
            text = state["next_question"]
            _emit({"type": "turn_start", "speaker": "host", "kind": "question", "block_idx": block_idx})
            _emit({"type": "token", "text": text})
            turn = _turn("host", "question", text, block_idx)
        else:
            first = _answer_order(state["questions_total"])[0]
            instruction = prompts.host_question(state["script"], block_idx, state["question_idx"], first)
            turn = await host_say(state, "question", instruction)
        return {
            "transcript": [turn],
            "question_idx": state["question_idx"] + 1,
            "next_question": None,
            "resume_step": None,
            **_start_question(state, turn.text, ["dogs", "cats"]),
        }

    async def host_decide(state: DebateState) -> dict[str, Any]:
        block = state["script"].blocks[state["block_idx"]]
        asked = state["question_idx"]
        if asked >= block.questions_max:
            _emit({"type": "decision", "block_exhausted": True, "reason": "questions_max"})
            return {"step": "block_summary"}
        must_continue = asked < block.questions_min
        first = _answer_order(state["questions_total"])[0]
        instruction = prompts.host_decide(state["script"], state["block_idx"], asked, must_continue, first)
        messages = prompts.host_messages(state, instruction)
        call_id = _model_start("host", "decide", messages, decision=True)
        try:
            decision = await decide(messages)
        except asyncio.CancelledError:
            _model_end(call_id, "host", "cancelled")
            raise
        except Exception:
            _model_end(call_id, "host", "error")
            raise
        _emit({"type": "model_result", "id": call_id, "model": "host", "parsed": decision.model_dump(mode="json")})
        _model_end(call_id, "host", "done", retain=True)
        exhausted = decision.block_exhausted and not must_continue
        _emit({"type": "decision", "block_exhausted": exhausted, "next_question": decision.next_question})
        if exhausted:
            return {"step": "block_summary"}
        # Brak pytania w decyzji: host_question wygeneruje je osobnym wywołaniem.
        return {"step": "question", "next_question": (decision.next_question or "").strip() or None}

    async def host_reprimand(state: DebateState) -> dict[str, Any]:
        pending = list(state["pending_director"])
        cmd = next(c for c in pending if isinstance(c, Reprimand))
        pending.remove(cmd)
        turn = await host_say(state, "reprimand", prompts.host_reprimand(cmd.target, cmd.reason))
        reprimands = {side: list(rs) for side, rs in state["reprimands"].items()}
        reprimands.setdefault(cmd.target, []).append(cmd.reason)
        _emit({"type": "director_ack", "id": cmd.id, "status": "done"})
        return {"transcript": [turn], "pending_director": pending, "reprimands": reprimands}

    async def host_extra_question(state: DebateState) -> dict[str, Any]:
        pending = list(state["pending_director"])
        cmd = next(c for c in pending if isinstance(c, ExtraQuestion))
        pending.remove(cmd)
        targets: list[Side] = ["dogs", "cats"] if cmd.target == "both" else [cmd.target]
        first = [s for s in _answer_order(state["questions_total"]) if s in targets][0]
        turn = await host_say(state, "question", prompts.host_extra_question(cmd.text, cmd.target, first))
        _emit({"type": "director_ack", "id": cmd.id, "status": "done"})
        return {
            "transcript": [turn],
            "pending_director": pending,
            **_start_question(state, turn.text, targets),
            # Po odpowiedziach wracamy tam, gdzie przebieg był (licznik bloku bez zmian).
            "resume_step": state["step"],
        }

    async def host_block_summary(state: DebateState) -> dict[str, Any]:
        script, block_idx = state["script"], state["block_idx"]
        closing_order = _closing_order(state)
        turn = await host_say(state, "block_summary", prompts.host_block_summary(script, block_idx, closing_order))
        if block_idx + 1 < len(script.blocks):
            return {"transcript": [turn], "block_idx": block_idx + 1, "step": "block_intro"}
        return {"transcript": [turn], **_after_blocks(state)}

    async def host_closing(state: DebateState) -> dict[str, Any]:
        turn = await host_say(state, "summary", prompts.host_closing())
        return {"transcript": [turn], **_phase("done"), "step": "done"}

    # --- debatanci -----------------------------------------------------------

    async def debater_answer(state: DebateState) -> dict[str, Any]:
        side, *rest = state["pending_speakers"]
        instruction = prompts.debater_answer(side, state["current_question"] or "")
        text, block_idx = await debater_say(state, side, "answer", instruction)
        turn = _turn(side, "answer", text, block_idx)
        update: dict[str, Any] = {"transcript": [turn], "pending_speakers": rest}
        if not rest and state["resume_step"]:
            update.update(step=state["resume_step"], resume_step=None)
        elif not rest:
            update["step"] = "decide"
        return update

    async def debater_closing(state: DebateState) -> dict[str, Any]:
        side, *rest = state["closing_order"]
        instruction = prompts.debater_closing(state["script"], side, state["script"].closing_statement.words)
        text, _ = await debater_say(state, side, "closing_statement", instruction)
        update: dict[str, Any] = {"transcript": [_turn(side, "closing_statement", text, None)], "closing_order": rest}
        if not rest:
            if state["script"].host_summary:
                update.update(_phase("closing"), step="closing")
            else:
                update.update(_phase("done"), step="done")
        return update

    nodes = {
        "host_opening": host_opening,
        "host_block_intro": host_block_intro,
        "host_question": host_question,
        "host_decide": host_decide,
        "host_reprimand": host_reprimand,
        "host_extra_question": host_extra_question,
        "host_block_summary": host_block_summary,
        "host_closing": host_closing,
        "debater_answer": debater_answer,
        "debater_closing": debater_closing,
    }
    graph = StateGraph(DebateState)
    graph.add_node("director_gate", director_gate)
    for name, fn in nodes.items():
        graph.add_node(name, fn)
        graph.add_edge(name, "director_gate")
    graph.add_edge(START, "director_gate")
    graph.add_conditional_edges("director_gate", route, [*nodes, END])
    return graph.compile(checkpointer=checkpointer or InMemorySaver())


def run_config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT}
