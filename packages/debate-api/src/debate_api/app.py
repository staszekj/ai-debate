"""FastAPI: REST + WebSocket nad grafem debaty.

    GET  /api/presets             lista gotowych schematów
    GET  /api/presets/{id}        jeden schemat
    POST /api/sessions            DebateScript → start debaty, zwraca session_id
    GET  /api/sessions/{id}       status sesji
    WS   /ws/sessions/{id}        zdarzenia debaty (z historią) i komendy reżysera
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from debate_api.sessions import DepsFactory, Session, SessionManager, default_deps
from debate_core.script import DebateScript, list_presets, load_preset
from debate_core.state import DirectorCommand


class Control(BaseModel):
    type: Literal["pause", "resume", "stop"]


IncomingCommand = TypeAdapter(Annotated[DirectorCommand | Control, Field(discriminator="type")])


class PresetInfo(BaseModel):
    id: str
    title: str


class SessionInfo(BaseModel):
    session_id: str
    status: str
    phase: str
    script: DebateScript


def _info(session: Session) -> SessionInfo:
    return SessionInfo(session_id=session.id, status=session.status, phase=session.phase, script=session.script)


def handle_command(session: Session, raw: dict[str, Any]) -> dict[str, Any]:
    """Wykonuje komendę reżysera i zwraca zdarzenie potwierdzenia (albo błędu) dla klienta."""
    try:
        cmd = IncomingCommand.validate_python(raw)
    except ValidationError as e:
        return {"type": "error", "message": "nieprawidłowa komenda", "details": e.errors(include_url=False)}
    if isinstance(cmd, Control):
        director = session.director
        {"pause": director.pause, "resume": director.resume, "stop": director.stop}[cmd.type]()
        status = {"pause": "paused", "resume": "running", "stop": "stopping"}[cmd.type]
        if cmd.type != "stop":
            session.publish({"type": "status", "status": status})
        return {"type": "control_ack", "command": cmd.type}
    session.director.send(cmd)
    ack = {"type": "director_ack", "id": cmd.id, "status": "queued", "command": cmd.model_dump()}
    session.publish(ack)  # historia: klient po ponownym połączeniu widzi wysłane komendy
    return ack


def create_app(deps_factory: DepsFactory = default_deps) -> FastAPI:
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

    @app.get("/api/presets")
    def presets() -> list[PresetInfo]:
        return [PresetInfo(id=p, title=load_preset(p).title) for p in list_presets()]

    @app.get("/api/presets/{preset_id}")
    def preset(preset_id: str) -> DebateScript:
        try:
            return load_preset(preset_id)
        except KeyError:
            raise HTTPException(404, "nie ma takiego presetu") from None

    @app.post("/api/sessions", status_code=201)
    async def create_session(script: DebateScript) -> SessionInfo:
        return _info(manager.create(script))

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
                if reply["type"] != "director_ack":  # ack komendy idzie do wszystkich przez historię
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
