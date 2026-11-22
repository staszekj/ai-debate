from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from debate_core.director import DirectorChannel, Side

TURNS_PER_EXPERT = 2
SEARCH_LIMIT = 2
Action = Literal["wikipedia", "dog_expert", "cat_expert"]
EXPERTS: dict[Side, Action] = {"dogs": "dog_expert", "cats": "cat_expert"}


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
    action: Action
    query: str | None = Field(description="Wikipedia search phrase for wikipedia; null for an expert")


class DebateState(TypedDict):
    question: str
    transcript: list[Speech]
    sources: list[Source]
    research_notes: list[str]
    queries: list[str]
    query: str
    action: Action | None
    summary: str
    preferred_expert: Side | None


@dataclass
class ExpertDebateDeps:
    brain_control: Callable[[ExpertInput, list[str], list[Action], Side | None], Awaitable[ResearchDecision]]
    search: Callable[[str], Awaitable[list[Source]]]
    reply: Callable[[Side, ExpertInput], Awaitable[str]]
    director: DirectorChannel
    summarize: Callable[[str, list[Speech]], Awaitable[str]]


def expert_input(state: DebateState) -> ExpertInput:
    return ExpertInput(question=state["question"], transcript=state["transcript"],
                       sources=state["sources"], research_notes=state["research_notes"])


def build_graph(deps: ExpertDebateDeps):
    async def human_control(state: DebateState) -> dict:
        await deps.director.checkpoint()
        preference = deps.director.take_expert_preference()
        return {"preferred_expert": preference} if preference is not None else {}

    async def brain_control(state: DebateState) -> dict:
        actions = [action for side, action in EXPERTS.items()
                   if sum(speech.speaker == side for speech in state["transcript"]) < TURNS_PER_EXPERT]
        if not actions:
            summary = (await deps.summarize(state["question"], state["transcript"])).strip()
            if not summary:
                raise ValueError("The coordinator returned an empty summary")
            if not await deps.director.checkpoint():
                get_stream_writer()({"type": "summary", "text": summary})
                return {"action": None, "summary": summary}
            return {"action": None}

        if len(state["queries"]) < SEARCH_LIMIT:
            actions.append("wikipedia")
        for _ in range(2):
            preference = state["preferred_expert"]
            if preference is not None and EXPERTS[preference] not in actions:
                preference = None
            decision = await deps.brain_control(expert_input(state), state["queries"], actions, preference)
            query = (decision.query or "").strip()[:300]
            if decision.action in actions and (decision.action != "wikipedia" or (
                query and query.casefold() not in {previous.casefold() for previous in state["queries"]}
            )):
                return {"action": decision.action, "query": query}
            if await deps.director.checkpoint():
                return {"action": None}
        raise ValueError("The coordinator did not select an allowed action")

    async def wikipedia(state: DebateState) -> dict:
        query = state["query"]
        emit = get_stream_writer()
        emit({"type": "research_start", "query": query})
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
        emit({"type": "research_end", "query": query, "status": status,
              "sources": [source.model_dump() for source in sources]})
        return {"sources": [*state["sources"], *sources], "research_notes": notes,
                "queries": [*state["queries"], query]}

    async def reply(state: DebateState, side: Side) -> dict:
        emit = get_stream_writer()
        emit({"type": "turn_start", "speaker": side})
        text = await deps.reply(side, expert_input(state))
        if deps.director.stopped:
            return {}
        speech = Speech(speaker=side, text=text)
        emit({"type": "turn_end", **speech.model_dump()})
        return {"transcript": [*state["transcript"], speech], "sources": [],
            "research_notes": [], "queries": [], "query": "", "preferred_expert": None}

    async def dog_expert(state: DebateState) -> dict:
        return await reply(state, "dogs")

    async def cat_expert(state: DebateState) -> dict:
        return await reply(state, "cats")

    def after_human_control(state: DebateState) -> str:
        return END if deps.director.stopped else "brain_control"

    async def after_brain_control(state: DebateState) -> str:
        if await deps.director.checkpoint():
            return END
        return state["action"] or END

    graph = StateGraph(DebateState)
    graph.add_node("human_control", human_control)
    graph.add_node("brain_control", brain_control)
    graph.add_node("wikipedia", wikipedia)
    graph.add_node("dog_expert", dog_expert)
    graph.add_node("cat_expert", cat_expert)
    graph.add_edge(START, "human_control")
    graph.add_conditional_edges("human_control", after_human_control, ["brain_control", END])
    graph.add_conditional_edges("brain_control", after_brain_control, ["wikipedia", "dog_expert", "cat_expert", END])
    for tool in ("wikipedia", "dog_expert", "cat_expert"):
        graph.add_edge(tool, "human_control")
    return graph.compile().with_config(recursion_limit=50)


def initial_state(question: str) -> DebateState:
    return {"question": question, "transcript": [], "sources": [], "research_notes": [],
            "queries": [], "query": "", "action": None, "summary": "", "preferred_expert": None}