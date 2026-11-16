"""Prompty (PL): prowadzący per krok, debatanci per krok.

Prowadzący widzi cały przebieg jako tekst i dostaje instrukcję bieżącego kroku.
Debatant widzi debatę ze swojej perspektywy (`build_debater_context`): własne
wypowiedzi jako `AIMessage`, cudze jako `HumanMessage` z prefiksem mówcy.
Tu w v2 dojdzie krok retrievalu (RAG), bez zmian w grafie.
"""

from __future__ import annotations

import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from debate_core.script import Block, DebateScript
from debate_core.state import DebateState, Side, Speaker, Turn, opponent

TEAM = {"dogs": "Psy", "cats": "Koty"}
ANIMAL = {"dogs": "pies", "cats": "kot"}
SPEAKER_LABEL: dict[Speaker, str] = {"host": "Prowadzący", "dogs": "Psy", "cats": "Koty"}
KIND_LABEL = {"ad_vocem": "ad vocem", "closing_statement": "mowa końcowa", "reprimand": "upomnienie"}

# Ile znaków transkryptu trafia do debatanta (Bielik, kontekst 16k tokenów).
DEBATER_TRANSCRIPT_CHARS = 16_000
PASS_TOKEN = "PASS"


# --- wspólne ---------------------------------------------------------------


def format_turn(turn: Turn) -> str:
    label = SPEAKER_LABEL[turn.speaker]
    if turn.kind in KIND_LABEL:
        label += f", {KIND_LABEL[turn.kind]}"
    return f"[{label}] {turn.text}"


def visible_turns(transcript: list[Turn]) -> list[Turn]:
    """Wypowiedzi, które faktycznie padły (bez pominiętych ad vocem)."""
    return [t for t in transcript if not t.passed and t.text]


def is_pass(text: str) -> bool:
    cleaned = text.strip().strip(".!\"'«»„”*").upper()
    return cleaned == PASS_TOKEN or (cleaned.startswith(PASS_TOKEN) and len(cleaned) <= len(PASS_TOKEN) + 3)


_SENTENCE_END = re.compile(r"(?<=[.!?…])[\"”»]?\s+")


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text.strip()) if s]


def trim_incomplete(text: str) -> str:
    """Obcina urwane zdanie na końcu (np. po limicie tokenów)."""
    text = text.strip()
    if not text or text[-1] in ".!?…\"”»)":
        return text
    sentences = split_sentences(text)
    return " ".join(sentences[:-1]) if len(sentences) > 1 else text


def limit_sentences(text: str, max_sentences: int) -> str:
    return " ".join(split_sentences(text)[:max_sentences])


def last_statement(state: DebateState, side: Side) -> str | None:
    """Ostatnia wypowiedź merytoryczna danej strony (odpowiedź, ad vocem, mowa)."""
    for turn in reversed(visible_turns(state["transcript"])):
        if turn.speaker == side:
            return turn.text
    return None


# --- prowadzący ------------------------------------------------------------


def host_system(script: DebateScript, notes: list[str]) -> str:
    text = (
        f"Prowadzisz debatę „{script.title}” między dwiema drużynami: „Psy” (broni tezy, że pies jest lepszym "
        "towarzyszem człowieka) i „Koty” (broni tezy, że lepszy jest kot). Publiczność słucha na żywo.\n"
        "Zasady:\n"
        "- Mówisz wyłącznie po polsku, naturalnie i zwięźle, jak moderator w studiu.\n"
        "- Jesteś bezstronny. Nigdy nie wskazujesz zwycięzcy ani nie oceniasz, kto ma rację.\n"
        "- Wypowiadasz tylko własną kwestię: bez didaskaliów, bez etykiet typu „Prowadzący:”, bez markdownu.\n"
        "- Pytania kierujesz do obu drużyn, chyba że instrukcja mówi inaczej."
    )
    if notes:
        text += (
            "\n\nUwagi od reżysera debaty (uwzględniaj je przy kolejnych pytaniach i komentarzach, "
            "ale nie wspominaj o reżyserze):\n" + "\n".join(f"- {n}" for n in notes)
        )
    return text


def host_messages(state: DebateState, instruction: str) -> list[BaseMessage]:
    script = state["script"]
    lines: list[str] = []
    for turn in visible_turns(state["transcript"]):
        if turn.kind == "block_intro" and turn.block_idx is not None:
            lines.append(f"\n=== Blok {turn.block_idx + 1}: {script.blocks[turn.block_idx].topic} ===")
        lines.append(format_turn(turn))
    history = "\n".join(lines).strip() or "(debata jeszcze się nie zaczęła)"
    return [
        SystemMessage(host_system(script, state["notes"])),
        HumanMessage(f"Dotychczasowy przebieg debaty:\n\n{history}\n\n---\nTwoje zadanie teraz: {instruction}"),
    ]


def _blocks_plan(script: DebateScript) -> str:
    return "; ".join(f"{i + 1}. {b.topic}" for i, b in enumerate(script.blocks))


def host_opening(script: DebateScript) -> str:
    return (
        "Otwórz debatę. Przywitaj publiczność, przedstaw temat, obie drużyny i plan debaty "
        f"(bloki tematyczne: {_blocks_plan(script)}). Nie zadawaj jeszcze pytań. 3–5 zdań."
    )


def _guidance(block: Block) -> str:
    return f" Wskazówki do bloku: {block.guidance}" if block.guidance else ""


def host_block_intro(script: DebateScript, block_idx: int) -> str:
    block = script.blocks[block_idx]
    return (
        f"Zapowiedz blok {block_idx + 1} z {len(script.blocks)}: „{block.topic}”.{_guidance(block)} "
        "Nie zadawaj jeszcze pytania. 1–2 zdania."
    )


def _first(first: Side) -> str:
    return f"Jako pierwsza odpowie drużyna „{TEAM[first]}” (możesz ją wywołać, nie wskazuj innej kolejności)."


def host_question(script: DebateScript, block_idx: int, question_idx: int, first: Side) -> str:
    block = script.blocks[block_idx]
    which = "pierwsze pytanie" if question_idx == 0 else "kolejne pytanie"
    return (
        f"Zadaj {which} w bloku „{block.topic}”.{_guidance(block)} Pytanie trafia do obu drużyn. "
        f"Poruszaj aspekty, których jeszcze nie omówiono. {_first(first)} "
        "Wypowiedz tylko samo pytanie, 1–2 zdania."
    )


def host_decide(script: DebateScript, block_idx: int, asked: int, must_continue: bool, first: Side) -> str:
    block = script.blocks[block_idx]
    rule = (
        "Temat nie może być jeszcze uznany za wyczerpany: przygotuj kolejne pytanie."
        if must_continue
        else "Uznaj temat za wyczerpany, jeśli kolejne pytanie powtarzałoby już omówione wątki."
    )
    return (
        f"W bloku „{block.topic}” padło już {asked} pytań (docelowo około {block.questions_target}, "
        f"najwyżej {block.questions_max}).{_guidance(block)} Zdecyduj, czy temat bloku jest wyczerpany. "
        f"{rule} Jeśli nie jest, sformułuj kolejne pytanie do obu drużyn (1–2 zdania), "
        "dotyczące aspektu, którego jeszcze nie poruszono, z uwzględnieniem uwag reżysera. "
        f"{_first(first)}"
    )


def host_reprimand(target: Side, reason: str) -> str:
    return (
        f"Reżyser prosi o upomnienie drużyny „{TEAM[target]}”. Powód: {reason}. Upomnij ją własnymi słowami, "
        "zwracając się bezpośrednio do tej drużyny: uprzejmie, ale stanowczo. 1–2 zdania."
    )


def host_extra_question(text: str, target: Side | str, first: Side) -> str:
    to = f"obu drużyn. {_first(first)}" if target == "both" else f"wyłącznie drużyny „{TEAM[target]}”."
    return (
        f"Zadaj teraz dodatkowe pytanie do {to} Jego treść (od reżysera): „{text}”. "
        "Przeformułuj je własnymi słowami jako pytanie prowadzącego i nie wspominaj o reżyserze. "
        "Wypowiedz tylko samo pytanie, 1–2 zdania."
    )


def host_block_summary(script: DebateScript, block_idx: int, closing_order: list[Side]) -> str:
    block = script.blocks[block_idx]
    is_last = block_idx == len(script.blocks) - 1
    if not is_last:
        nxt = f"Zapowiedz przejście do kolejnego bloku: „{script.blocks[block_idx + 1].topic}”."
    elif script.closing_statement.enabled:
        order = ", a potem ".join(f"„{TEAM[s]}”" for s in closing_order)
        nxt = f"Zapowiedz mowy końcowe obu drużyn: najpierw {order}."
    else:
        nxt = "Zapowiedz zakończenie debaty."
    return (
        f"Krótko podsumuj blok „{block.topic}”: najważniejsze argumenty obu stron, bezstronnie, "
        f"bez wskazywania zwycięzcy. {nxt} 2–4 zdania."
    )


def host_closing() -> str:
    return (
        "Zakończ debatę: krótko i bezstronnie podsumuj najważniejsze argumenty obu drużyn, bez werdyktu "
        "i bez wskazywania zwycięzcy. Podziękuj drużynom i publiczności. 3–5 zdań."
    )


# --- debatanci -------------------------------------------------------------


def debater_system(side: Side, reprimands: list[str]) -> str:
    team, animal = TEAM[side], ANIMAL[side]
    other_team, other_animal = TEAM[opponent(side)], ANIMAL[opponent(side)]
    text = (
        f"Jesteś drużyną „{team}” w publicznej debacie „psy kontra koty”. Bronisz tezy, że {animal} jest "
        f"lepszym towarzyszem człowieka niż {other_animal}. Przeciwnikiem jest drużyna „{other_team}”, "
        "a debatę prowadzi Prowadzący.\n"
        "Zasady:\n"
        "- Mówisz wyłącznie po polsku, w pierwszej osobie liczby mnogiej (my, nasza drużyna).\n"
        "- Argumentujesz rzeczowo i z werwą, ale kulturalnie. Nie obrażasz przeciwnika.\n"
        "- Odpowiadasz na to, o co pytano. Nie wychodzisz z roli i nie wspominasz, że jesteś modelem językowym.\n"
        "- Wypowiadasz tylko własną kwestię: bez etykiet typu „Psy:”, bez nagłówków i bez list punktowanych.\n"
        "- Mówisz zwięźle i od razu do rzeczy. Nie zaczynasz od formułek typu „Jako drużyna…”, "
        "„Uważamy, że…” ani od powtarzania pytania."
    )
    if reprimands:
        text += "\n\nProwadzący upomniał już waszą drużynę. Bezwzględnie się do tego zastosuj:\n" + "\n".join(
            f"- {r}" for r in reprimands
        )
    return text


def debater_ad_vocem(side: Side, max_sentences: int, opponent_statement: str) -> str:
    return (
        f"Ad vocem. Ostatnia wypowiedź drużyny „{TEAM[opponent(side)]}” brzmiała: „{opponent_statement}”\n"
        f"Odnieś się krótko do tej wypowiedzi: wskaż słaby punkt albo sprostuj, maksymalnie w {max_sentences} "
        "zdaniach. Nie odpowiadaj jeszcze na pytanie Prowadzącego, na to przyjdzie czas za chwilę. "
        f"Jeśli nie masz nic istotnego do dodania, odpowiedz wyłącznie słowem {PASS_TOKEN}."
    )


def debater_answer(side: Side, question: str) -> str:
    return (
        f"Odpowiedz na pytanie Prowadzącego: „{question}”. Przedstaw stanowisko drużyny „{TEAM[side]}” "
        "w 3–5 zdaniach (najwyżej około 80 słów), z jednym konkretnym argumentem lub przykładem."
    )


def debater_closing(side: Side, words: int) -> str:
    return (
        f"Wygłoś mowę końcową drużyny „{TEAM[side]}”, zwracając się bezpośrednio do publiczności: "
        f"w około {words} słowach powiedz, dlaczego {ANIMAL[side]} jest lepszy dla człowieka. "
        "Nawiąż do najmocniejszych argumentów z debaty."
    )


def build_debater_context(state: DebateState, side: Side, instruction: str) -> list[BaseMessage]:
    """Wiadomości dla debatanta: prompt strony + upomnienia + przycięty transkrypt + instrukcja kroku."""
    turns = visible_turns(state["transcript"])
    kept: list[Turn] = []
    budget = DEBATER_TRANSCRIPT_CHARS
    for turn in reversed(turns):
        budget -= len(turn.text) + 20
        if budget < 0:
            break
        kept.append(turn)
    kept.reverse()

    # (rola, tekst); kolejne wiadomości tej samej roli są scalane, bo szablony czatu
    # części modeli wymagają naprzemienności user/assistant.
    parts: list[tuple[str, str]] = []
    if len(kept) < len(turns):
        parts.append(("user", "(Wcześniejsza część debaty została pominięta.)"))
    for turn in kept:
        if turn.speaker == side:
            parts.append(("assistant", turn.text))
        else:
            parts.append(("user", format_turn(turn)))
    parts.append(("user", f"[Instrukcja] {instruction}"))

    merged: list[tuple[str, str]] = []
    for role, text in parts:
        if merged and merged[-1][0] == role:
            merged[-1] = (role, merged[-1][1] + "\n\n" + text)
        else:
            merged.append((role, text))

    messages: list[BaseMessage] = [SystemMessage(debater_system(side, state["reprimands"].get(side, [])))]
    messages += [AIMessage(t) if role == "assistant" else HumanMessage(t) for role, t in merged]
    return messages
