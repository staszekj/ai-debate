"""Testy REST i WebSocketu debate-api na zamockowanych modelach."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from debate_api.app import create_app
from debate_api.sessions import Session
from debate_core.director import DirectorChannel
from debate_core.script import load_preset
from debate_core.testing import Decider, make_deps

MINI = {
    "title": "Test",
    "positions": {"dogs": "Więcej zieleni.", "cats": "Więcej mieszkań."},
    "blocks": [{"topic": "Temat", "questions_min": 1, "questions_target": 2, "questions_max": 2}],
}


def fake_deps(delay: float = 0.0) -> Any:
    def factory(director: DirectorChannel) -> Any:
        return make_deps(director=director, decider=Decider(exhausted=True), delay=delay)

    return factory


@pytest.fixture
def client() -> Any:
    with TestClient(create_app(fake_deps())) as c:
        yield c


def read_until_end(ws: WebSocketTestSession) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while True:
        event = ws.receive_json()
        events.append(event)
        if event["type"] == "status" and event["status"] in ("done", "stopped", "error"):
            return events


def test_presets(client: TestClient) -> None:
    presets = client.get("/api/presets").json()
    assert {"id": "psy-vs-koty", "title": load_preset("psy-vs-koty").title} in presets
    assert client.get("/api/presets/psy-vs-koty").json()["blocks"][0]["topic"] == "Więź emocjonalna człowiek–zwierzę"
    assert client.get("/api/presets/nie-ma").status_code == 404
    assert "ad_vocem" not in client.get("/api/presets/psy-vs-koty").json()


def test_create_session_validates_script(client: TestClient) -> None:
    assert client.post("/api/sessions", json={"title": "x", "blocks": []}).status_code == 422
    response = client.post("/api/sessions", json={**MINI, "ad_vocem": {"enabled": False}})
    assert response.status_code == 422
    assert "pole ad_vocem zostało usunięte" in response.text
    assert client.post("/api/sessions", json={**MINI, "positions": {"dogs": " ", "cats": "x"}}).status_code == 422
    assert client.post("/api/sessions", json={key: value for key, value in MINI.items() if key != "positions"}).status_code == 422


def test_ws_streams_full_debate_with_history(client: TestClient) -> None:
    session = client.post("/api/sessions", json=MINI).json()
    assert session["status"] == "running"
    assert session["script"]["positions"] == MINI["positions"]
    with client.websocket_connect(f"/ws/sessions/{session['session_id']}") as ws:
        events = read_until_end(ws)
    types = [e["type"] for e in events]
    assert types[0] == "status" and events[0]["status"] == "running"
    assert {"turn_start", "token", "turn_end", "phase", "decision"} <= set(types)
    kinds = [e["kind"] for e in events if e["type"] == "turn_end"]
    assert kinds[0] == "intro" and kinds[-1] == "summary"
    assert "ad_vocem" not in kinds
    assert all("passed" not in e for e in events if e["type"] == "turn_end")
    starts = [i for i, e in enumerate(events) if e["type"] == "turn_start" and e["kind"] == "answer"]
    assert starts
    for i in starts:
        end = next(j for j in range(i + 1, len(events)) if events[j]["type"] == "turn_end")
        assert any(e["type"] == "token" for e in events[i + 1 : end])
    fetched = client.get(f"/api/sessions/{session['session_id']}").json()
    assert fetched["status"] == "done"
    assert fetched["script"]["positions"] == MINI["positions"]

    # drugi klient po zakończeniu dostaje całą historię
    with client.websocket_connect(f"/ws/sessions/{session['session_id']}") as ws:
        replay = read_until_end(ws)
    assert [e for e in replay if not e["type"].startswith("model_")] == [
        e for e in events if not e["type"].startswith("model_")
    ]


def test_model_snapshots_and_reconnect() -> None:
    session = Session(id="test", script=load_preset("psy-vs-koty"), director=DirectorChannel())
    session.publish({"type": "status", "status": "running"})
    first = {"type": "model_start", "id": "one", "model": "dogs", "step": "answer", "messages": []}
    chunk = {"type": "model_chunk", "id": "one", "model": "dogs", "chunk": {"content": "  tekst "}}
    session.publish(first)
    session.publish(chunk)
    queue = session.subscribe()
    assert [queue.get_nowait() for _ in range(3)] == [session.events[0], first, chunk]
    next_chunk = {"type": "model_chunk", "id": "one", "model": "dogs", "chunk": {"content": "dalej"}}
    session.publish(next_chunk)
    assert queue.get_nowait() == next_chunk
    session.publish({"type": "model_end", "id": "one", "model": "dogs", "status": "done", "retain": False})
    assert not session._model_calls

    start = {"type": "model_start", "id": "two", "model": "host", "step": "decide", "messages": []}
    result = {"type": "model_result", "id": "two", "model": "host", "parsed": {"block_exhausted": True}}
    end = {"type": "model_end", "id": "two", "model": "host", "status": "done", "retain": True}
    for event in (start, result, end):
        session.publish(event)
    session.publish({"type": "status", "status": "done"})
    replay = session.subscribe()
    assert [replay.get_nowait() for _ in range(6)] == [session.events[0], start, result, end, session.events[-1], None]
    assert all(not e["type"].startswith("model_") for e in session.events)
    next_start = {"type": "model_start", "id": "three", "model": "host", "step": "summary", "messages": []}
    session.publish(next_start)
    assert session._model_calls["host"] == [next_start]


def test_session_error_clears_active_model_call() -> None:
    session = Session(id="test", script=load_preset("psy-vs-koty"), director=DirectorChannel())
    session.publish({"type": "model_start", "id": "one", "model": "cats", "step": "answer", "messages": []})
    queue = session.subscribe()
    queue.get_nowait()
    session.publish({"type": "status", "status": "error", "message": "błąd"})
    assert queue.get_nowait() == {
        "type": "model_end", "id": "one", "model": "cats", "status": "error", "retain": False
    }
    assert queue.get_nowait()["status"] == "error"
    assert not session._model_calls


def test_ws_director_commands() -> None:
    with TestClient(create_app(fake_deps(delay=0.02))) as client:
        sid = client.post("/api/sessions", json=MINI).json()["session_id"]
        with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
            ws.send_json({"type": "reprimand", "id": "rep1", "target": "cats", "reason": "dygresje"})
            ws.send_json({"type": "note", "id": "note1", "text": "dociśnij koty"})
            ws.send_json({"type": "extra_question", "id": "xq1", "text": "Co z alergiami?", "target": "dogs"})
            ws.send_json({"type": "bogus"})
            events = read_until_end(ws)

    acks = [(e["id"], e["status"]) for e in events if e["type"] == "director_ack"]
    for cid in ("rep1", "note1", "xq1"):
        assert (cid, "queued") in acks and (cid, "done") in acks
    assert any(e["type"] == "error" for e in events)
    reprimands = [e for e in events if e["type"] == "turn_end" and e["kind"] == "reprimand"]
    assert len(reprimands) == 1 and reprimands[0]["speaker"] == "host"


def test_ws_pause_resume_stop() -> None:
    with TestClient(create_app(fake_deps(delay=0.02))) as client:
        sid = client.post("/api/sessions", json=MINI).json()["session_id"]
        with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
            ws.send_json({"type": "pause"})
            ws.send_json({"type": "resume"})
            ws.send_json({"type": "stop"})
            events = read_until_end(ws)
    statuses = [e["status"] for e in events if e["type"] == "status"]
    assert "paused" in statuses and statuses[-1] == "stopped"
    assert [e["command"] for e in events if e["type"] == "control_ack"] == ["pause", "resume", "stop"]
    assert client.get(f"/api/sessions/{sid}").json()["status"] == "stopped"


def test_ws_unknown_session(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/sessions/nope") as ws:
        ws.receive_json()
