"""FastAPI: REST + WebSocket nad grafem debaty.

    POST /api/sessions            pytanie → start debaty, zwraca session_id
    GET  /api/sessions/{id}       status sesji
    WS   /ws/sessions/{id}        zdarzenia debaty (z historią) i komendy reżysera
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, StringConstraints, ValidationError

from debate_api.sessions import DepsFactory, Session, SessionManager
from debate_core.mcp_service import make_expert_deps


class Control(BaseModel):
    type: Literal["pause", "resume", "stop"]


class SessionRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class SessionInfo(BaseModel):
    session_id: str
    status: str
    question: str


def _info(session: Session) -> SessionInfo:
    return SessionInfo(session_id=session.id, status=session.status, question=session.question)


def handle_command(session: Session, raw: dict[str, Any]) -> dict[str, Any]:
    """Wykonuje komendę reżysera i zwraca zdarzenie potwierdzenia (albo błędu) dla klienta."""
    try:
        cmd = Control.model_validate(raw)
    except ValidationError:
        return {"type": "error", "message": "Nieprawidłowa komenda."}
    if session.finished or session.director.stopped:
        return {"type": "error", "message": "Sesja nie przyjmuje już poleceń."}
    director = session.director
    {"pause": director.pause, "resume": director.resume, "stop": director.stop}[cmd.type]()
    status = {"pause": "paused", "resume": "running", "stop": "stopping"}[cmd.type]
    session.publish({"type": "status", "status": status})
    return {"type": "control_ack", "command": cmd.type}


def create_app(deps_factory: DepsFactory = make_expert_deps) -> FastAPI:
    manager = SessionManager(deps_factory)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await manager.shutdown()

    app = FastAPI(title="ai-debate", lifespan=lifespan)

    def session_or_404(session_id: str) -> Session:
        session = manager.get(session_id)
        if session is None:
            raise HTTPException(404, "nie ma takiej sesji")
        return session

    @app.post("/api/sessions", status_code=201)
    async def create_session(request: SessionRequest) -> SessionInfo:
        return _info(manager.create(request.question))

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> SessionInfo:
        return _info(session_or_404(session_id))

    @app.websocket("/ws/sessions/{session_id}")
    async def session_ws(websocket: WebSocket, session_id: str) -> None:
        session = manager.get(session_id)
        if session is None:
            await websocket.close(code=4404, reason="nie ma takiej sesji")
            return
        await websocket.accept()
        queue = session.subscribe()

        async def send_events() -> None:
            while (event := await queue.get()) is not None:
                await websocket.send_json(event)

        async def receive_commands() -> None:
            while True:
                try:
                    raw = await websocket.receive_json()
                except ValueError:
                    await websocket.send_json({"type": "error", "message": "oczekiwano JSON"})
                    continue
                reply = handle_command(session, raw if isinstance(raw, dict) else {})
                if reply["type"] == "error":
                    await websocket.send_json(reply)

        sender, receiver = asyncio.create_task(send_events()), asyncio.create_task(receive_commands())
        try:
            done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                if (exc := task.exception()) and not isinstance(exc, WebSocketDisconnect):
                    raise exc
        finally:
            session.unsubscribe(queue)
        if sender in done:  # koniec sesji: zamykamy połączenie
            await websocket.close()

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("debate_api.app:app", host="127.0.0.1", port=8001)
