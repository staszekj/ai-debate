"""Sesje debaty: `thread_id` → zadanie grafu + `DirectorChannel` + historia zdarzeń.

Zdarzenia debaty trafiają do historii, a diagnostyka modeli do bieżących
migawek. Klient po połączeniu dostaje migawki i historię debaty.
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
    _model_calls: dict[str, list[Event]] = field(default_factory=dict)

    def publish(self, event: Event) -> None:
        event_type = event.get("type")
        if event_type == "model_start":
            self._model_calls[event["model"]] = [event]
        elif event_type in ("model_chunk", "model_result", "model_end"):
            call = self._model_calls.get(event["model"])
            if not call or call[0]["id"] != event["id"]:
                raise ValueError("zdarzenie diagnostyczne nie pasuje do aktywnego wywołania")
            if event_type == "model_end" and not event["retain"]:
                del self._model_calls[event["model"]]
            else:
                call.append(event)
        else:
            if event_type == "status" and event["status"] in ("done", "stopped", "error"):
                self._end_active_calls("error" if event["status"] == "error" else "cancelled")
            self.events.append(event)
        if event.get("type") == "phase":
            self.phase = event["phase"]
        if event.get("type") == "status":
            self.status = event["status"]
        for q in self._subscribers:
            q.put_nowait(event)

    def _end_active_calls(self, status: str) -> None:
        for model, events in list(self._model_calls.items()):
            if events[-1]["type"] != "model_end":
                self.publish({"type": "model_end", "id": events[0]["id"], "model": model, "status": status, "retain": False})

    def subscribe(self) -> asyncio.Queue[Event | None]:
        """Kolejka z dotychczasową historią i kolejnymi zdarzeniami; `None` = koniec sesji."""
        q: asyncio.Queue[Event | None] = asyncio.Queue()
        if self.events:
            q.put_nowait(self.events[0])
        for events in self._model_calls.values():
            for event in events:
                q.put_nowait(event)
        for event in self.events[1:]:
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
            self._end_active_calls("cancelled")
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
