"""Testy routera i grafu na fake modelach: przebieg, liczniki, kolejność, interwencje."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from debate_core.director import DirectorChannel
from debate_core.graph import DebateDeps, build_graph, run_config
from debate_core.script import Block, ClosingStatement, DebateScript, load_preset
from debate_core.state import ExtraQuestion, Note, Reprimand, Turn, initial_state

from debate_core.testing import Decider, ScriptedChatModel, default_debater, default_host, last_text, make_deps


def script(blocks: int = 2, qmin: int = 2, qtarget: int = 3, qmax: int = 4, **kwargs: Any) -> DebateScript:
    return DebateScript(
        title="Test",
        blocks=[
            Block(topic=f"Temat {i}", questions_min=qmin, questions_target=qtarget, questions_max=qmax)
            for i in range(blocks)
        ],
        **kwargs,
    )


async def run(s: DebateScript, deps: DebateDeps) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    graph = build_graph(deps)
    events: list[dict[str, Any]] = []
    final: dict[str, Any] = {}
    async for mode, chunk in graph.astream(initial_state(s), run_config("t"), stream_mode=["custom", "values"]):
        if mode == "custom":
            events.append(chunk)
        else:
            final = chunk
    return final, events


def kinds(transcript: list[Turn]) -> list[str]:
    return [t.kind for t in transcript]


def questions_per_block(transcript: list[Turn]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for t in transcript:
        if t.kind == "question" and t.block_idx is not None:
            counts[t.block_idx] = counts.get(t.block_idx, 0) + 1
    return counts


def answer_orders(transcript: list[Turn]) -> list[list[str]]:
    """Kolejność odpowiadających na kolejne pytania."""
    orders: list[list[str]] = []
    for t in transcript:
        if t.kind == "question":
            orders.append([])
        elif t.kind == "answer":
            orders[-1].append(t.speaker)
    return orders


# --- przebieg ----------------------------------------------------------------


async def test_phase_order() -> None:
    final, events = await run(script(blocks=2), make_deps())
    ks = kinds(final["transcript"])
    assert ks[0] == "intro"
    assert ks.count("block_intro") == 2 and ks.count("block_summary") == 2
    assert ks[-3:] == ["closing_statement", "closing_statement", "summary"]
    assert final["phase"] == "done"
    assert [e["phase"] for e in events if e["type"] == "phase"] == ["block", "closing_statements", "closing", "done"]
    # bloki idą po kolei, każdy zaczyna się zapowiedzią i kończy podsumowaniem
    block_turns = [(t.kind, t.block_idx) for t in final["transcript"] if t.kind in ("block_intro", "block_summary")]
    assert block_turns == [("block_intro", 0), ("block_summary", 0), ("block_intro", 1), ("block_summary", 1)]


async def test_preset_runs_end_to_end() -> None:
    final, _ = await run(load_preset("psy-vs-koty"), make_deps(decider=Decider(exhausted=False)))
    assert questions_per_block(final["transcript"]) == {0: 6, 1: 6, 2: 6}
    assert final["phase"] == "done"


@pytest.mark.parametrize(("exhausted", "expected"), [(True, 2), (False, 4)])
async def test_question_count_within_min_max(exhausted: bool, expected: int) -> None:
    decider = Decider(exhausted=exhausted)
    final, _ = await run(script(blocks=2, qmin=2, qmax=4), make_deps(decider=decider))
    assert questions_per_block(final["transcript"]) == {0: expected, 1: expected}


async def test_decide_question_is_used_verbatim() -> None:
    final, _ = await run(script(blocks=1, qmin=2, qtarget=2, qmax=2), make_deps(decider=Decider(False, "Pytanie z decyzji?")))
    questions = [t.text for t in final["transcript"] if t.kind == "question"]
    assert questions == ["Jakie jest wasze zdanie?", "Pytanie z decyzji?"]


async def test_no_decide_call_at_questions_max() -> None:
    decider = Decider(exhausted=False)
    await run(script(blocks=1, qmin=1, qtarget=2, qmax=3), make_deps(decider=decider))
    assert len(decider.calls) == 2  # po 1. i 2. pytaniu; po 3. kod sam kończy blok


async def test_answer_order_alternates() -> None:
    final, _ = await run(script(blocks=2, qmin=3, qtarget=3, qmax=3), make_deps(decider=Decider(False)))
    orders = answer_orders(final["transcript"])
    assert len(orders) == 6
    for i, order in enumerate(orders):
        assert order == (["dogs", "cats"] if i % 2 == 0 else ["cats", "dogs"])


async def test_questions_are_followed_by_direct_answers() -> None:
    final, events = await run(script(blocks=1, qmin=2, qtarget=2, qmax=2), make_deps(decider=Decider(False)))
    seq = [(t.speaker, t.kind) for t in final["transcript"] if t.kind in ("question", "answer")]
    assert seq == [
        ("host", "question"),
        ("dogs", "answer"),
        ("cats", "answer"),
        ("host", "question"),
        ("cats", "answer"),
        ("dogs", "answer"),
    ]
    ends = [e for e in events if e["type"] == "turn_end" and e["kind"] == "ad_vocem"]
    assert not ends
    assert all("passed" not in e for e in events if e["type"] == "turn_end")


async def test_model_diagnostics_capture_messages_and_untrimmed_output() -> None:
    deps = make_deps(debater=lambda _: "  Pełne zdanie. Urwana końcówka  ", decider=Decider(False))
    final, events = await run(script(blocks=1, qmin=2, qtarget=2, qmax=2), deps)
    starts = [event for event in events if event["type"] == "model_start"]
    for model, fake in [("host", deps.host), *deps.debaters.items()]:
        calls = [e for e in starts if e["model"] == model and e["step"] != "decide"]
        assert [e["messages"] for e in calls] == [
            [message.model_dump(mode="json") for message in messages] for messages in fake.calls
        ]
    decision_start = next(e for e in starts if e["step"] == "decide")
    assert decision_start["messages"] == [m.model_dump(mode="json") for m in deps.decide.calls[0]]
    assert "block_exhausted" in decision_start["response_schema"]["properties"]
    assert next(e["parsed"] for e in events if e["type"] == "model_result") == {
        "block_exhausted": False, "next_question": "Następne pytanie?"
    }
    answer_start = next(e for e in starts if e["step"] == "answer")
    chunks = [e["chunk"]["content"] for e in events if e["type"] == "model_chunk" and e["id"] == answer_start["id"]]
    assert "".join(chunks) == "  Pełne zdanie. Urwana końcówka  "
    assert next(t.text for t in final["transcript"] if t.kind == "answer") == "Pełne zdanie."
    assert all(
        sum(e["type"] == "model_end" and e["id"] == start["id"] for e in events) == 1 for start in starts
    )
    question_starts = [e for e in starts if e["model"] == "host" and e["step"] == "question"]
    assert len(question_starts) == 1  # drugie pytanie pochodzi z decyzji


async def test_model_diagnostics_preserve_nontext_blocks() -> None:
    class BlockModel(ScriptedChatModel):
        def _stream(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> Any:
            yield ChatGenerationChunk(message=AIMessageChunk(content=[
                {"type": "reasoning", "reasoning": "Udostępniony blok"},
                {"type": "text", "text": "Odpowiedź."},
            ]))

    deps = make_deps()
    deps.debaters["dogs"] = BlockModel(respond=default_debater)
    _, events = await run(script(blocks=1, qmin=1, qtarget=1, qmax=1), deps)
    start = next(e for e in events if e["type"] == "model_start" and e["model"] == "dogs")
    chunk = next(e["chunk"] for e in events if e["type"] == "model_chunk" and e["id"] == start["id"])
    assert chunk["content"] == [
        {"type": "reasoning", "reasoning": "Udostępniony blok"},
        {"type": "text", "text": "Odpowiedź."},
    ]


async def test_decider_error_remains_a_failure() -> None:
    async def fail(_: Any) -> Any:
        raise ValueError("nieprawidłowa decyzja")

    deps = make_deps()
    deps.decide = fail
    with pytest.raises(ValueError, match="nieprawidłowa decyzja"):
        await run(script(blocks=1, qmin=2, qtarget=2, qmax=2), deps)


async def test_closing_statements_reverse_order_and_length() -> None:
    deps = make_deps()
    final, _ = await run(script(blocks=1, closing_statement=ClosingStatement(words=80)), deps)
    closing = [t.speaker for t in final["transcript"] if t.kind == "closing_statement"]
    assert closing == ["cats", "dogs"]  # pierwsze pytanie: psy, potem koty
    closing_calls = [c for m in deps.debaters.values() for c in m.calls if "mowę końcową" in last_text(c)]
    assert len(closing_calls) == 2 and all("około 80 słowach" in last_text(c) for c in closing_calls)


async def test_closing_disabled_and_no_host_summary() -> None:
    s = script(blocks=1, closing_statement=ClosingStatement(enabled=False), host_summary=False)
    final, _ = await run(s, make_deps())
    assert kinds(final["transcript"])[-1] == "block_summary"
    assert final["phase"] == "done"


# --- interwencje reżysera ------------------------------------------------------


def host_triggering(trigger: str, action: Any) -> Any:
    """Prowadzący, który przy instrukcji zawierającej `trigger` wykonuje `action` (raz)."""
    fired = False

    def respond(messages: Any) -> str:
        nonlocal fired
        if not fired and trigger in last_text(messages):
            fired = True
            action()
        return default_host(messages)

    return respond


async def test_reprimand_goes_to_host_and_debater_context() -> None:
    director = DirectorChannel()
    host = host_triggering("Otwórz debatę", lambda: director.send(Reprimand(target="cats", reason="obrażanie psów")))
    deps = make_deps(host=host, director=director)
    final, events = await run(script(blocks=1), deps)

    turns = final["transcript"]
    assert kinds(turns)[:2] == ["intro", "reprimand"]
    assert turns[1].speaker == "host"
    reprimand_calls = [c for c in deps.host.calls if "Reżyser prosi o upomnienie" in last_text(c)]
    assert len(reprimand_calls) == 1 and "obrażanie psów" in last_text(reprimand_calls[0])
    assert final["reprimands"] == {"dogs": [], "cats": ["obrażanie psów"]}
    # upomnienie trafia do system promptu kotów, ale nie psów
    assert deps.debaters["cats"].calls and all("obrażanie psów" in c[0].content for c in deps.debaters["cats"].calls)
    assert not any("obrażanie psów" in c[0].content for c in deps.debaters["dogs"].calls)
    acks = [(e["status"]) for e in events if e["type"] == "director_ack"]
    assert acks == ["pending", "done"]


async def test_extra_question_is_next_and_does_not_count() -> None:
    director = DirectorChannel()
    extra = ExtraQuestion(text="Co z alergiami?", target="cats")
    host = host_triggering("Otwórz debatę", lambda: director.send(extra))
    deps = make_deps(host=host, director=director, decider=Decider(exhausted=True))
    final, _ = await run(script(blocks=1, qmin=2, qtarget=2, qmax=3), deps)

    turns = final["transcript"]
    # zaraz po zapowiedzi bloku: dodatkowe pytanie, odpowiadają tylko koty
    assert kinds(turns)[1:4] == ["block_intro", "question", "answer"]
    assert turns[3].speaker == "cats"
    extra_calls = [c for c in deps.host.calls if "dodatkowe pytanie" in last_text(c)]
    assert len(extra_calls) == 1 and "Co z alergiami?" in last_text(extra_calls[0])
    # licznik bloku bez zmian: nadal dokładnie questions_min zwykłych pytań + 1 dodatkowe
    assert questions_per_block(turns) == {0: 3}
    assert final["question_idx"] == 2


async def test_extra_question_waits_for_answers_to_finish() -> None:
    director = DirectorChannel()

    def debater(messages: Any) -> str:
        if "Odpowiedz na pytanie" in last_text(messages) and not director_sent:
            director_sent.append(True)
            director.send(ExtraQuestion(text="Pytanie reżysera"))
        return default_debater(messages)

    director_sent: list[bool] = []
    final, _ = await run(script(blocks=1, qmin=1, qtarget=1, qmax=2), make_deps(debater=debater, director=director))
    seq = [(t.speaker, t.kind) for t in final["transcript"] if t.kind in ("question", "answer")]
    # pierwsza wymiana kończy się normalnie (obie odpowiedzi), dopiero potem dodatkowe pytanie
    assert seq[:3] == [("host", "question"), ("dogs", "answer"), ("cats", "answer")]
    assert seq[3] == ("host", "question")


@pytest.mark.parametrize(("target", "expected"), [("dogs", ["dogs"]), ("cats", ["cats"]), ("both", ["dogs", "cats"])])
async def test_extra_question_direct_answers(target: str, expected: list[str]) -> None:
    director = DirectorChannel()
    extra = ExtraQuestion(text="Dodatkowe pytanie?", target=target)
    host = host_triggering("Otwórz debatę", lambda: director.send(extra))
    final, _ = await run(script(blocks=1, qmin=1, qtarget=1, qmax=1), make_deps(host=host, director=director))
    turns = final["transcript"]
    question_idx = next(i for i, t in enumerate(turns) if t.kind == "question")
    assert [(t.kind, t.speaker) for t in turns[question_idx + 1 : question_idx + 1 + len(expected)]] == [
        ("answer", side) for side in expected
    ]


async def test_reprimand_can_interrupt_between_answers() -> None:
    director = DirectorChannel()
    sent: list[bool] = []

    def debater(messages: Any) -> str:
        if not sent:
            sent.append(True)
            director.send(Reprimand(target="cats", reason="bez dygresji"))
        return default_debater(messages)

    final, _ = await run(
        script(blocks=1, qmin=1, qtarget=1, qmax=1),
        make_deps(debater=debater, director=director),
    )
    turns = final["transcript"]
    question_idx = next(i for i, t in enumerate(turns) if t.kind == "question")
    assert [(t.kind, t.speaker) for t in turns[question_idx + 1 : question_idx + 4]] == [
        ("answer", "dogs"), ("reprimand", "host"), ("answer", "cats")
    ]


async def test_note_reaches_host_system_prompt() -> None:
    director = DirectorChannel()
    host = host_triggering("Otwórz debatę", lambda: director.send(Note(text="dociśnij koty o alergie")))
    deps = make_deps(host=host, director=director)
    await run(script(blocks=1), deps)
    first, later = deps.host.calls[0], deps.host.calls[1:]
    assert "dociśnij koty o alergie" not in first[0].content
    assert later and all("dociśnij koty o alergie" in c[0].content for c in later)


async def test_pause_and_resume() -> None:
    director = DirectorChannel()
    host = host_triggering("Zapowiedz blok", director.pause)
    deps = make_deps(host=host, director=director)
    events: list[dict[str, Any]] = []

    async def consume() -> None:
        graph = build_graph(deps)
        async for chunk in graph.astream(initial_state(script(blocks=1)), run_config("p"), stream_mode="custom"):
            events.append(chunk)

    task = asyncio.create_task(consume())
    for _ in range(100):
        if director.paused:
            break
        await asyncio.sleep(0.01)
    assert director.paused
    await asyncio.sleep(0.1)
    count = len(events)
    await asyncio.sleep(0.2)
    assert len(events) == count, "graf powinien stać w director_gate"
    assert not task.done()
    assert {"type": "status", "status": "paused"} in events
    director.resume()
    await asyncio.wait_for(task, timeout=5)
    assert events[-1] == {"type": "phase", "phase": "done"}


async def test_stop() -> None:
    director = DirectorChannel()
    host = host_triggering("Zapowiedz blok", director.stop)
    final, events = await run(script(blocks=2), make_deps(host=host, director=director))
    assert final["phase"] == "stopped"
    assert kinds(final["transcript"]) == ["intro", "block_intro"]
    assert {"type": "status", "status": "stopped"} in events
