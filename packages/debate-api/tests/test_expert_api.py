from fastapi.testclient import TestClient

from debate_api.app import create_app
from debate_core.expert_graph import ExpertDebateDeps, ResearchDecision, Source


def test_session_delivers_four_turns_and_replays_research():
    seen = []

    async def coordinate(side, context, queries):
        assert context.question == "Psy czy koty?"
        query = f"dog {len(queries)}" if side == "dogs" else None
        return ResearchDecision(query=query)

    async def search(query):
        if query == "dog 0":
            return [Source(title="Pies", url="https://pl.wikipedia.org/wiki/Pies", excerpt="Fragment")]
        raise OSError("offline")

    async def reply(side, context):
        seen.append((side, len(context.sources), len(context.research_notes), len(context.transcript)))
        return side.upper()

    with TestClient(create_app(lambda director: ExpertDebateDeps(coordinate, search, reply, director))) as client:
        assert client.post("/api/sessions", json={"question": "  "}).status_code == 422
        response = client.post("/api/sessions", json={"question": "Psy czy koty?"})
        assert response.status_code == 201
        path = f"/ws/sessions/{response.json()['session_id']}"

        def receive():
            with client.websocket_connect(path) as socket:
                events = []
                while True:
                    event = socket.receive_json()
                    events.append(event)
                    if event["type"] == "status" and event["status"] in {"done", "error", "stopped"}:
                        return events

        events = receive()
        assert events[-1]["status"] == "done"
        assert [event["speaker"] for event in events if event["type"] == "turn_end"] == ["dogs", "cats", "dogs", "cats"]
        assert [event["status"] for event in events if event["type"] == "research_end"] == ["found", "unavailable"] * 2
        assert seen == [("dogs", 1, 1, 0), ("cats", 0, 0, 1), ("dogs", 1, 1, 2), ("cats", 0, 0, 3)]
        assert receive() == events