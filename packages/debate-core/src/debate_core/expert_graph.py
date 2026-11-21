from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from debate_core.director import DirectorChannel

Side = Literal["dogs", "cats"]
ORDER: tuple[Side, ...] = ("dogs", "cats", "dogs", "cats")
SEARCH_LIMIT = 2


class Source(BaseModel):
    title: str
    url: str
    excerpt: str


class Speech(BaseModel):
    speaker: Side
    text: str


class ExpertInput(BaseModel):
    question: str
    transcript: list[Speech]
    sources: list[Source]
    research_notes: list[str]


class ResearchDecision(BaseModel):
    query: str | None = Field(description="Wikipedia search query, or null when ready to consult the expert")


class DebateState(TypedDict):
    question: str
    transcript: list[Speech]
    sources: list[Source]
    research_notes: list[str]
    queries: list[str]
    query: str


@dataclass
class ExpertDebateDeps:
    coordinate: Callable[[Side, ExpertInput, list[str]], Awaitable[ResearchDecision]]
    search: Callable[[str], Awaitable[list[Source]]]
    reply: Callable[[Side, ExpertInput], Awaitable[str]]
    director: DirectorChannel


def expert_input(state: DebateState) -> ExpertInput:
    return ExpertInput(question=state["question"], transcript=state["transcript"],
                       sources=state["sources"], research_notes=state["research_notes"])


def build_expert_graph(deps: ExpertDebateDeps):
    async def gate(state: DebateState) -> dict:
        if len(state["transcript"]) < len(ORDER):
            await deps.director.checkpoint()
        return {}

    async def coordinate(state: DebateState) -> dict:
        side = ORDER[len(state["transcript"])]
        decision = await deps.coordinate(side, expert_input(state), state["queries"])
        query = (decision.query or "").strip()
        return {"query": query[:300]}

    async def search(state: DebateState) -> dict:
        query = state["query"]
        emit = get_stream_writer()
        side = ORDER[len(state["transcript"])]
        emit({"type": "research_start", "speaker": side, "query": query})
        notes = state["research_notes"]
        try:
            sources = await deps.search(query)
            status = "found" if sources else "empty"
            if not sources:
                notes = [*notes, f"Wikipedia returned no sources for: {query}"]
        except Exception:
            sources = []
            status = "unavailable"
            notes = [*notes, f"Wikipedia search unavailable for: {query}"]
        emit({"type": "research_end", "speaker": side, "query": query, "status": status,
              "sources": [source.model_dump() for source in sources]})
        return {"sources": [*state["sources"], *sources], "research_notes": notes,
                "queries": [*state["queries"], query]}

    async def reply(state: DebateState) -> dict:
        side = ORDER[len(state["transcript"])]
        emit = get_stream_writer()
        emit({"type": "turn_start", "speaker": side})
        text = await deps.reply(side, expert_input(state))
        if deps.director.stopped:
            return {}
        speech = Speech(speaker=side, text=text)
        emit({"type": "turn_end", **speech.model_dump()})
        return {"transcript": [*state["transcript"], speech], "sources": [],
                "research_notes": [], "queries": [], "query": ""}

    def after_gate(state: DebateState) -> str:
        if deps.director.stopped or len(state["transcript"]) >= len(ORDER):
            return END
        return "reply" if len(state["queries"]) >= SEARCH_LIMIT else "coordinate"

    async def after_decision(state: DebateState) -> str:
        if await deps.director.checkpoint():
            return END
        return "search" if state["query"] and state["query"] not in state["queries"] else "reply"

    graph = StateGraph(DebateState)
    graph.add_node("gate", gate)
    graph.add_node("coordinate", coordinate)
    graph.add_node("search", search)
    graph.add_node("reply", reply)
    graph.add_edge(START, "gate")
    graph.add_conditional_edges("gate", after_gate, ["coordinate", "reply", END])
    graph.add_conditional_edges("coordinate", after_decision, ["search", "reply", END])
    graph.add_edge("search", "gate")
    graph.add_edge("reply", "gate")
    return graph.compile().with_config(recursion_limit=50)


def initial_expert_state(question: str) -> DebateState:
    return {"question": question, "transcript": [], "sources": [], "research_notes": [],
            "queries": [], "query": ""}