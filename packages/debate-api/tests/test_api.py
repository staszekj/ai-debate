"""Testy REST i WebSocketu debate-api na zamockowanych modelach."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from debate_api.app import create_app
from debate_core.director import DirectorChannel
from debate_core.script import load_preset
from debate_core.testing import Decider, make_deps

MINI = {
    "title": "Test",
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


def test_create_session_validates_script(client: TestClient) -> None:
    assert client.post("/api/sessions", json={"title": "x", "blocks": []}).status_code == 422


def test_ws_streams_full_debate_with_history(client: TestClient) -> None:
    session = client.post("/api/sessions", json=MINI).json()
    assert session["status"] == "running"
    with client.websocket_connect(f"/ws/sessions/{session['session_id']}") as ws:
        events = read_until_end(ws)
    types = [e["type"] for e in events]
    assert types[0] == "status" and events[0]["status"] == "running"
    assert {"turn_start", "token", "turn_end", "phase", "decision"} <= set(types)
    kinds = [e["kind"] for e in events if e["type"] == "turn_end"]
    assert kinds[0] == "intro" and kinds[-1] == "summary"
    assert client.get(f"/api/sessions/{session['session_id']}").json()["status"] == "done"

    # drugi klient po zakończeniu dostaje całą historię
    with client.websocket_connect(f"/ws/sessions/{session['session_id']}") as ws:
        assert read_until_end(ws) == events


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
