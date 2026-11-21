"""In-memory debate sessions with live events and history replay."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from debate_core.director import DirectorChannel
from debate_core.expert_graph import ExpertDebateDeps, build_expert_graph, initial_expert_state
from debate_core.mcp_service import make_expert_deps

log = logging.getLogger(__name__)

DepsFactory = Callable[[DirectorChannel], ExpertDebateDeps]
Event = dict[str, Any]


@dataclass
class Session:
    id: str
    question: str
    director: DirectorChannel
    events: list[Event] = field(default_factory=list)
    status: str = "running"  # running | paused | stopped | done | error
    task: asyncio.Task[None] | None = None
    _subscribers: set[asyncio.Queue[Event | None]] = field(default_factory=set)

    def publish(self, event: Event) -> None:
        self.events.append(event)
        if event.get("type") == "status":
            self.status = event["status"]
        for q in self._subscribers:
            q.put_nowait(event)

    def subscribe(self) -> asyncio.Queue[Event | None]:
        """Kolejka z dotychczasową historią i kolejnymi zdarzeniami; `None` = koniec sesji."""
        q: asyncio.Queue[Event | None] = asyncio.Queue()
        for event in self.events:
            q.put_nowait(event)
        if self.finished:
            q.put_nowait(None)
        else:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event | None]) -> None:
        self._subscribers.discard(q)

    @property
    def finished(self) -> bool:
        return self.status in ("stopped", "done", "error")

    def _close(self) -> None:
        for q in self._subscribers:
            q.put_nowait(None)
        self._subscribers.clear()

    async def run(self, deps: ExpertDebateDeps) -> None:
        graph = build_expert_graph(deps)
        try:
            async for event in graph.astream(initial_expert_state(self.question), stream_mode="custom"):
                self.publish(event)
            self.publish({"type": "status", "status": "stopped" if self.director.stopped else "done"})
        except Exception:
            log.exception("sesja %s zakończona błędem", self.id)
            self.publish({"type": "status", "status": "error", "message": "Nie udało się dokończyć debaty."})
        finally:
            self._close()


class SessionManager:
    def __init__(self, deps_factory: DepsFactory = make_expert_deps) -> None:
        self._deps_factory = deps_factory
        self._sessions: dict[str, Session] = {}

    def create(self, question: str) -> Session:
        director = DirectorChannel()
        session = Session(id=uuid.uuid4().hex[:12], question=question, director=director)
        self._sessions[session.id] = session
        session.publish({"type": "status", "status": "running"})
        session.task = asyncio.create_task(session.run(self._deps_factory(director)))
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def shutdown(self) -> None:
        for session in self._sessions.values():
            session.director.stop()
            if session.task and not session.task.done():
                session.task.cancel()
