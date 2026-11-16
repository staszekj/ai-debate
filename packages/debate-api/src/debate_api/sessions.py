"""Sesje debaty: `thread_id` → zadanie grafu + `DirectorChannel` + historia zdarzeń.

Każde zdarzenie z grafu trafia do historii sesji i do kolejek podłączonych
klientów. Klient, który podłączy się później (albo po zerwaniu połączenia),
najpierw dostaje całą historię, więc nie traci początku debaty.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from debate_core.director import DirectorChannel
from debate_core.graph import DebateDeps, build_graph, run_config
from debate_core.llms import make_debater, make_decider, make_host
from debate_core.script import DebateScript
from debate_core.state import SIDES, initial_state

log = logging.getLogger(__name__)

DepsFactory = Callable[[DirectorChannel], DebateDeps]
Event = dict[str, Any]


def default_deps(director: DirectorChannel) -> DebateDeps:
    host = make_host()
    return DebateDeps(
        host=host,
        decide=make_decider(host),
        debaters={side: make_debater(side) for side in SIDES},
        director=director,
    )


@dataclass
class Session:
    id: str
    script: DebateScript
    director: DirectorChannel
    events: list[Event] = field(default_factory=list)
    status: str = "running"  # running | paused | stopped | done | error
    phase: str = "opening"
    task: asyncio.Task[None] | None = None
    _subscribers: set[asyncio.Queue[Event | None]] = field(default_factory=set)

    def publish(self, event: Event) -> None:
        if event.get("type") == "phase":
            self.phase = event["phase"]
        if event.get("type") == "status":
            self.status = event["status"]
        self.events.append(event)
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

    async def run(self, deps: DebateDeps) -> None:
        graph = build_graph(deps)
        try:
            async for event in graph.astream(initial_state(self.script), run_config(self.id), stream_mode="custom"):
                self.publish(event)
            if not self.director.stopped:
                self.publish({"type": "status", "status": "done"})
        except Exception as e:  # noqa: BLE001 — błąd modelu kończy sesję, klient dostaje komunikat
            log.exception("sesja %s zakończona błędem", self.id)
            self.publish({"type": "status", "status": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            self._close()


class SessionManager:
    def __init__(self, deps_factory: DepsFactory = default_deps) -> None:
        self._deps_factory = deps_factory
        self._sessions: dict[str, Session] = {}

    def create(self, script: DebateScript) -> Session:
        director = DirectorChannel()
        session = Session(id=uuid.uuid4().hex[:12], script=script, director=director)
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
