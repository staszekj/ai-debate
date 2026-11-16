import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from debate_core import prompts
from debate_core.script import Block, list_presets, load_preset
from debate_core.state import Turn, initial_state


def test_preset_psy_vs_koty() -> None:
    assert "psy-vs-koty" in list_presets()
    s = load_preset("psy-vs-koty")
    assert [b.topic for b in s.blocks] == [
        "Więź emocjonalna człowiek–zwierzę",
        "Obowiązki człowieka wobec zwierzęcia",
        "Koszty weterynaryjne",
    ]
    assert all(b.questions_target == 5 for b in s.blocks)
    assert s.ad_vocem.enabled and s.closing_statement.words == 100


def test_block_rejects_bad_question_range() -> None:
    with pytest.raises(ValidationError):
        Block(topic="x", questions_min=5, questions_target=3, questions_max=6)


@pytest.mark.parametrize("text", ["PASS", "pass", " PASS. ", "**PASS**", "„PASS”"])
def test_is_pass(text: str) -> None:
    assert prompts.is_pass(text)


@pytest.mark.parametrize("text", ["", "Passa to nie jest", "PASS, ale chcemy dodać, że psy są lepsze"])
def test_is_not_pass(text: str) -> None:
    assert not prompts.is_pass(text)


def test_debater_context_perspective_and_merging() -> None:
    state = initial_state(load_preset("psy-vs-koty"))
    state["transcript"] = [
        Turn(speaker="host", kind="intro", text="Witamy."),
        Turn(speaker="host", kind="question", text="Pytanie?", block_idx=0),
        Turn(speaker="dogs", kind="answer", text="Psy odpowiadają.", block_idx=0),
        Turn(speaker="cats", kind="ad_vocem", text="", block_idx=0, passed=True),
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
    assert "ad vocem" not in msgs[3].content  # pominięte ad vocem nie trafia do kontekstu


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


def test_limit_sentences() -> None:
    text = "Raz. Dwa! Trzy? Cztery."
    assert prompts.limit_sentences(text, 3) == "Raz. Dwa! Trzy?"
    assert prompts.limit_sentences(text, 10) == text


def test_ad_vocem_instruction_quotes_opponent() -> None:
    instruction = prompts.debater_ad_vocem("cats", 3, "Psy są najwierniejsze.")
    assert "„Psy są najwierniejsze.”" in instruction and "PASS" in instruction
