import pytest

from debate_core.cli import TerminalPrinter, parse_director_command, transcript_markdown
from debate_core.director import DirectorChannel
from debate_core.script import load_preset
from debate_core.state import ExtraQuestion, Note, Reprimand, Turn


async def drain(director: DirectorChannel) -> list:
    commands, _ = await director.checkpoint()
    return commands


async def test_reprimand_command() -> None:
    d = DirectorChannel()
    parse_director_command("/upomnij koty za dużo dygresji", d)
    [cmd] = await drain(d)
    assert isinstance(cmd, Reprimand) and cmd.target == "cats" and cmd.reason == "za dużo dygresji"


@pytest.mark.parametrize(
    ("line", "target", "text"),
    [("/pytanie psy Co ze spacerami?", "dogs", "Co ze spacerami?"), ("/p Co z kosztami?", "both", "Co z kosztami?")],
)
async def test_extra_question_command(line: str, target: str, text: str) -> None:
    d = DirectorChannel()
    parse_director_command(line, d)
    [cmd] = await drain(d)
    assert isinstance(cmd, ExtraQuestion) and cmd.target == target and cmd.text == text


async def test_note_pause_stop_and_usage() -> None:
    d = DirectorChannel()
    parse_director_command("/notatka dociśnij koty o alergie", d)
    [cmd] = await drain(d)
    assert isinstance(cmd, Note) and cmd.text == "dociśnij koty o alergie"
    parse_director_command("/pauza", d)
    assert d.paused
    parse_director_command("/wznow", d)
    assert not d.paused
    assert "użycie" in parse_director_command("/upomnij ktoś", d)
    assert "/pomoc" in parse_director_command("/cokolwiek", d)
    parse_director_command("/stop", d)
    assert d.stopped


def test_transcript_markdown() -> None:
    script = load_preset("psy-vs-koty")
    md = transcript_markdown(
        script,
        [
            Turn(speaker="host", kind="block_intro", text="Blok pierwszy.", block_idx=0),
            Turn(speaker="cats", kind="answer", text="Kocia odpowiedź.", block_idx=0),
            Turn(speaker="dogs", kind="closing_statement", text="Pies!"),
            Turn(speaker="cats", kind="closing_statement", text="Kot!"),
        ],
    )
    assert "## Blok 1: Więź emocjonalna człowiek–zwierzę" in md
    assert "**Koty:** Kocia odpowiedź." in md
    assert md.count("## Mowy końcowe") == 1


def test_terminal_printer_streams_answer(capsys: pytest.CaptureFixture[str]) -> None:
    printer = TerminalPrinter(load_preset("psy-vs-koty"), color=False)
    printer.handle({"type": "turn_start", "speaker": "dogs", "kind": "answer", "block_idx": 0})
    printer.handle({"type": "token", "text": "Nasz "})
    assert capsys.readouterr().out == "\nPsy: Nasz "
    printer.handle({"type": "token", "text": "argument."})
    printer.handle({"type": "turn_end"})
    assert capsys.readouterr().out == "argument.\n"
