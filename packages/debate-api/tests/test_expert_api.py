from fastapi.testclient import TestClient

from debate_api.app import create_app
from debate_core.graph import ExpertDebateDeps, ResearchDecision, Source


def test_session_delivers_four_turns_and_replays_research():
    seen = []

    async def brain_control(context, queries, actions, preferred_expert):
        assert context.question == "Psy czy koty?"
        assert preferred_expert is None
        if not context.transcript and "wikipedia" in actions:
            return ResearchDecision(action="wikipedia", query=f"cat {len(queries)}")
        action = "cat_expert" if len(context.transcript) < 2 else "dog_expert"
        if len(context.transcript) == 2:
            assert "cat_expert" not in actions
        return ResearchDecision(action=action, query=None)

    async def search(query):
        if query == "cat 0":
            return [Source(title="Kot", url="https://pl.wikipedia.org/wiki/Kot", excerpt="Fragment")]
        raise OSError("offline")

    async def reply(side, context):
        seen.append((side, len(context.sources), len(context.research_notes), len(context.transcript)))
        return side.upper()

    async def summarize(question, transcript):
        assert question == "Psy czy koty?"
        assert [speech.speaker for speech in transcript] == ["cats", "cats", "dogs", "dogs"]
        return "Podsumowanie obu stanowisk"

    with TestClient(create_app(lambda director: ExpertDebateDeps(brain_control, search, reply, director, summarize))) as client:
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
        assert [event["speaker"] for event in events if event["type"] == "turn_end"] == ["cats", "cats", "dogs", "dogs"]
        assert [event["status"] for event in events if event["type"] == "research_end"] == ["found", "unavailable"]
        assert events[-2] == {"type": "summary", "text": "Podsumowanie obu stanowisk"}
        assert seen == [("cats", 1, 1, 0), ("cats", 0, 0, 1), ("dogs", 0, 0, 2), ("dogs", 0, 0, 3)]
        assert receive() == events


def test_director_suggestion_survives_search_but_does_not_force_expert():
    preferences = []

    async def brain_control(context, queries, actions, preferred_expert):
        preferences.append(preferred_expert)
        if not context.transcript and not queries:
            return ResearchDecision(action="wikipedia", query="kot")
        action = "cat_expert" if "cat_expert" in actions else "dog_expert"
        return ResearchDecision(action=action, query=None)

    async def search(query):
        return []

    async def reply(side, context):
        return side

    async def summarize(question, transcript):
        return "Podsumowanie"

    def deps(director):
        director.pause()
        return ExpertDebateDeps(brain_control, search, reply, director, summarize)

    with TestClient(create_app(deps)) as client:
        session_id = client.post("/api/sessions", json={"question": "Psy czy koty?"}).json()["session_id"]
        with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
            socket.send_json({"type": "suggest_expert", "side": "dogs"})
            socket.send_json({"type": "resume"})
            events = []
            while (event := socket.receive_json()).get("status") not in {"done", "error"}:
                events.append(event)
            assert event["status"] == "done"

    assert {"type": "expert_suggested", "side": "dogs"} in events
    assert next(event for event in events if event["type"] == "turn_end")["speaker"] == "cats"
    assert preferences == ["dogs", "dogs", None, None, None]