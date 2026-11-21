import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from debate_core import prompts
from debate_core.script import Block, DebateScript, list_presets, load_preset
from debate_core.state import Turn, initial_state

POSITIONS = {"dogs": "Więcej zieleni.", "cats": "Więcej mieszkań."}


def test_preset_psy_vs_koty() -> None:
    assert "psy-vs-koty" in list_presets()
    s = load_preset("psy-vs-koty")
    assert [b.topic for b in s.blocks] == [
        "Więź emocjonalna człowiek–zwierzę",
        "Obowiązki człowieka wobec zwierzęcia",
        "Koszty weterynaryjne",
    ]
    assert all(b.questions_target == 5 for b in s.blocks)
    assert s.closing_statement.words == 100
    assert "ad_vocem" not in s.model_dump()


def test_block_rejects_bad_question_range() -> None:
    with pytest.raises(ValidationError):
        Block(topic="x", questions_min=5, questions_target=3, questions_max=6)


@pytest.mark.parametrize("value", [None, {"enabled": False}, {"enabled": True, "max_sentences": 3}])
def test_removed_ad_vocem_field_is_rejected(value: object) -> None:
    with pytest.raises(ValidationError, match="pole ad_vocem zostało usunięte"):
        DebateScript.model_validate({"title": "Test", "blocks": [{"topic": "Temat"}], "ad_vocem": value})


def test_other_unknown_script_fields_are_ignored() -> None:
    script = DebateScript.model_validate({"title": "Test", "positions": POSITIONS, "blocks": [{"topic": "Temat"}], "other": 1})
    assert "other" not in script.model_dump()


@pytest.mark.parametrize("positions", [None, {}, {"dogs": "x"}, {"dogs": "", "cats": "x"}, {"dogs": "x", "cats": " \n"}])
def test_positions_are_required_and_not_blank(positions: object) -> None:
    with pytest.raises(ValidationError):
        DebateScript.model_validate({"title": "Test", "positions": positions, "blocks": [{"topic": "Temat"}]})


def test_custom_topic_and_positions_in_prompts() -> None:
    script = DebateScript.model_validate({
        "title": "Przyszłość miast",
        "positions": POSITIONS,
        "blocks": [{"topic": "Przestrzeń publiczna"}],
    })
    host = prompts.host_system(script, [])
    assert script.title in host
    assert all(position in host for position in POSITIONS.values())
    for side in ("dogs", "cats"):
        system = prompts.debater_system(script, side, [])
        assert script.title in system
        assert all(position in system for position in POSITIONS.values())
        assert f"Twoje stanowisko: {POSITIONS[side]}" in system
        assert POSITIONS[side] in prompts.debater_closing(script, side, 100)


def test_debater_context_perspective_and_merging() -> None:
    state = initial_state(load_preset("psy-vs-koty"))
    state["transcript"] = [
        Turn(speaker="host", kind="intro", text="Witamy."),
        Turn(speaker="host", kind="question", text="Pytanie?", block_idx=0),
        Turn(speaker="dogs", kind="answer", text="Psy odpowiadają.", block_idx=0),
        Turn(speaker="cats", kind="answer", text="", block_idx=0),
        Turn(speaker="cats", kind="answer", text="Koty odpowiadają.", block_idx=0),
    ]
    state["reprimands"] = {"dogs": ["mniej krzyku"], "cats": []}
    msgs = prompts.build_debater_context(state, "dogs", "Instrukcja kroku.")

    assert isinstance(msgs[0], SystemMessage) and "mniej krzyku" in msgs[0].content
    roles = [type(m) for m in msgs[1:]]
    assert roles == [HumanMessage, AIMessage, HumanMessage]  # scalone, naprzemienne
    assert "[Prowadzący] Witamy." in msgs[1].content and "[Prowadzący] Pytanie?" in msgs[1].content
    assert msgs[2].content == "Psy odpowiadają."
    assert "[Koty] Koty odpowiadają." in msgs[3].content and msgs[3].content.endswith("[Instrukcja] Instrukcja kroku.")


def test_debater_context_truncates_old_turns() -> None:
    state = initial_state(load_preset("psy-vs-koty"))
    state["transcript"] = [
        Turn(speaker="host" if i % 2 else "cats", kind="answer", text=f"{i} " + "x" * 2000) for i in range(30)
    ]
    msgs = prompts.build_debater_context(state, "dogs", "Instrukcja.")
    body = "".join(str(m.content) for m in msgs[1:])
    assert "pominięta" in body
    assert "29 " in body and "\n0 " not in body
    assert len(body) < prompts.DEBATER_TRANSCRIPT_CHARS + 2000


def test_trim_incomplete() -> None:
    assert prompts.trim_incomplete("Pierwsze zdanie. Drugie urwane w poło") == "Pierwsze zdanie."
    assert prompts.trim_incomplete("Całe zdanie.") == "Całe zdanie."
    assert prompts.trim_incomplete("Jedno urwane") == "Jedno urwane"  # nie zostawiamy pustego tekstu
