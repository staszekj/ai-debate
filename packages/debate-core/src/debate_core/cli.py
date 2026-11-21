"""CLI `debate`.

    debate check                      ping prowadzącego i serwera debatantów (Bielik)
    debate run [--preset ID] [--script PLIK.json] [--out PLIK.md]
                                      pełna debata w terminalu; w trakcie można
                                      wpisywać komendy reżysera (/pomoc)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel

from debate_core.config import Settings, get_settings
from debate_core.director import DirectorChannel
from debate_core.graph import DebateDeps, build_graph, run_config
from debate_core.llms import make_debater, make_decider, make_host
from debate_core.prompts import SPEAKER_LABEL
from debate_core.script import DebateScript, list_presets, load_preset
from debate_core.state import SIDES, ExtraQuestion, Note, Reprimand, Side, Turn, initial_state


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def _ping_chat(name: str, make_model: Callable[[], BaseChatModel], prompt: str) -> CheckResult:
    t0 = time.perf_counter()
    try:
        reply = make_model().invoke(prompt)
    except Exception as e:  # noqa: BLE001 — każdy błąd to po prostu nieudany check
        return CheckResult(name, False, f"{type(e).__name__}: {e}")
    dt = time.perf_counter() - t0
    text = reply.text.strip().replace("\n", " ")
    usage = reply.usage_metadata or {}
    out_tokens = usage.get("output_tokens")
    speed = f", {out_tokens / dt:.1f} tok/s" if out_tokens else ""
    return CheckResult(name, bool(text), f"{dt:.1f}s{speed} → {text!r}")


def _check_served_model(base_url: str, model: str, api_key: str) -> CheckResult:
    name = f"serwer {base_url}"
    try:
        r = httpx.get(f"{base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=5)
        r.raise_for_status()
    except httpx.HTTPError as e:
        return CheckResult(name, False, f"brak połączenia ({e}). Czy działa infra/vllm.sh?")
    served = [m["id"] for m in r.json().get("data", [])]
    if model not in served:
        return CheckResult(name, False, f"model {model!r} nieobecny, serwer udostępnia: {served}")
    return CheckResult(name, True, f"udostępnia {model!r}")


def run_checks(settings: Settings) -> list[CheckResult]:
    results: list[CheckResult] = []

    results.append(
        _ping_chat(
            f"prowadzący ({settings.host_model})",
            lambda: make_host(settings, max_tokens=60),
            "Odpowiedz po polsku jednym krótkim zdaniem: przywitaj uczestników debaty.",
        )
    )

    # Strony mogą dzielić serwer; każdy unikalny serwer sprawdzamy raz.
    for base_url in dict.fromkeys(settings.base_url_for(side) for side in SIDES):
        served = _check_served_model(base_url, settings.debater_model, settings.debater_api_key)
        results.append(served)
        if not served.ok:
            continue
        sides = [side for side in SIDES if settings.base_url_for(side) == base_url]
        results.append(
            _ping_chat(
                f"debatant {'/'.join(sides)} ({settings.debater_model})",
                lambda side=sides[0]: make_debater(side, settings, max_tokens=80, timeout=120, max_retries=0),
                "Przedstaw się jednym zdaniem po polsku.",
            )
        )
    return results


def cmd_check(_: argparse.Namespace) -> int:
    results = run_checks(get_settings())
    for r in results:
        print(f"[{'OK' if r.ok else 'BŁĄD'}] {r.name}: {r.detail}")
    ok = all(r.ok for r in results)
    print("Wszystko działa." if ok else "Część sprawdzeń nie przeszła.")
    return 0 if ok else 1


# --- debate run --------------------------------------------------------------

HELP = """Komendy reżysera (wpisz i naciśnij Enter):
  /upomnij psy|koty <powód>          prowadzący upomina drużynę
  /pytanie [psy|koty|obie] <treść>   dodatkowe pytanie (domyślnie do obu)
  /notatka <treść>                   wskazówka dla prowadzącego
  /pauza  /wznow  /stop  /pomoc"""

SIDE_ALIASES: dict[str, Side] = {"psy": "dogs", "pies": "dogs", "dogs": "dogs", "koty": "cats", "kot": "cats", "cats": "cats"}
COLORS = {"host": "\033[1m", "dogs": "\033[33m", "cats": "\033[36m", "dim": "\033[2m", "reset": "\033[0m"}
KIND_SUFFIX = {"closing_statement": " (mowa końcowa)", "reprimand": " (upomnienie)"}


def parse_director_command(line: str, director: DirectorChannel) -> str:
    """Wykonuje komendę reżysera z linii tekstu i zwraca komunikat dla użytkownika."""
    cmd, _, rest = line.strip().partition(" ")
    cmd, rest = cmd.lower(), rest.strip()
    if cmd in ("/upomnij", "/u"):
        who, _, reason = rest.partition(" ")
        if who.lower() not in SIDE_ALIASES or not reason.strip():
            return "użycie: /upomnij psy|koty <powód>"
        cid = director.send(Reprimand(target=SIDE_ALIASES[who.lower()], reason=reason.strip()))
        return f"upomnienie {cid} w kolejce"
    if cmd in ("/pytanie", "/p"):
        who, _, text = rest.partition(" ")
        target: Side | str = "both"
        if who.lower() in SIDE_ALIASES:
            target = SIDE_ALIASES[who.lower()]
        elif who.lower() in ("obie", "both"):
            target = "both"
        else:
            text = rest
        if not text.strip():
            return "użycie: /pytanie [psy|koty|obie] <treść>"
        cid = director.send(ExtraQuestion(text=text.strip(), target=target))  # type: ignore[arg-type]
        return f"dodatkowe pytanie {cid} w kolejce"
    if cmd in ("/notatka", "/n"):
        if not rest:
            return "użycie: /notatka <treść>"
        return f"notatka {director.send(Note(text=rest))} w kolejce"
    if cmd in ("/pauza", "/pause"):
        director.pause()
        return "pauza po bieżącej wypowiedzi"
    if cmd in ("/wznow", "/wznów", "/resume"):
        director.resume()
        return "wznowiono"
    if cmd == "/stop":
        director.stop()
        return "stop po bieżącej wypowiedzi"
    return HELP


class TerminalPrinter:
    def __init__(self, script: DebateScript, color: bool) -> None:
        self.script = script
        self.color = color

    def c(self, key: str, text: str) -> str:
        return f"{COLORS[key]}{text}{COLORS['reset']}" if self.color else text

    def info(self, text: str) -> None:
        print(self.c("dim", f"[{text}]"), flush=True)

    def handle(self, e: dict[str, Any]) -> None:
        kind = e.get("kind")
        if e["type"] == "turn_start":
            if kind == "block_intro":
                idx = e["block_idx"]
                print(self.c("host", f"\n=== Blok {idx + 1}/{len(self.script.blocks)}: {self.script.blocks[idx].topic} ==="))
            label = SPEAKER_LABEL[e["speaker"]] + KIND_SUFFIX.get(kind, "")
            print("\n" + self.c(e["speaker"], label + ":"), end=" ", flush=True)
        elif e["type"] == "token":
            print(e["text"], end="", flush=True)
        elif e["type"] == "turn_end":
            print(flush=True)
        elif e["type"] == "decision":
            what = "temat wyczerpany" if e["block_exhausted"] else "kolejne pytanie"
            self.info(f"decyzja prowadzącego: {what}")
        elif e["type"] == "director_ack":
            self.info(f"reżyser: komenda {e['id']} {'zrealizowana' if e['status'] == 'done' else 'przyjęta'}")
        elif e["type"] == "status":
            self.info({"paused": "debata wstrzymana (/wznow)", "stopped": "debata przerwana przez reżysera"}[e["status"]])


def transcript_markdown(script: DebateScript, transcript: list[Turn]) -> str:
    lines = [f"# {script.title}", ""]
    in_closing = False
    for t in transcript:
        if t.kind == "block_intro" and t.block_idx is not None:
            lines += [f"## Blok {t.block_idx + 1}: {script.blocks[t.block_idx].topic}", ""]
        if t.kind == "closing_statement" and not in_closing:
            in_closing = True
            lines += ["## Mowy końcowe", ""]
        label = SPEAKER_LABEL[t.speaker] + KIND_SUFFIX.get(t.kind, "")
        lines += [f"**{label}:** {t.text}", ""]
    return "\n".join(lines)


def load_script(args: argparse.Namespace) -> DebateScript:
    if args.script:
        return DebateScript.model_validate(json.loads(Path(args.script).read_text(encoding="utf-8")))
    return load_preset(args.preset)


async def run_debate(script: DebateScript, settings: Settings, out: Path | None, interactive: bool) -> int:
    host = make_host(settings)
    director = DirectorChannel()
    deps = DebateDeps(
        host=host,
        decide=make_decider(host),
        debaters={side: make_debater(side, settings) for side in SIDES},
        director=director,
    )
    graph = build_graph(deps)
    printer = TerminalPrinter(script, color=sys.stdout.isatty())
    loop = asyncio.get_running_loop()

    if interactive:
        def on_stdin() -> None:
            line = sys.stdin.readline()
            if line.strip():
                printer.info(parse_director_command(line, director))

        loop.add_reader(sys.stdin.fileno(), on_stdin)
        printer.info("debata startuje; /pomoc pokazuje komendy reżysera")

    t0 = time.perf_counter()
    final: dict[str, Any] = {}
    try:
        async for mode, chunk in graph.astream(
            initial_state(script), run_config(uuid.uuid4().hex), stream_mode=["custom", "values"]
        ):
            if mode == "custom":
                printer.handle(chunk)
            else:
                final = chunk
    finally:
        if interactive:
            loop.remove_reader(sys.stdin.fileno())

    transcript: list[Turn] = final.get("transcript", [])
    per_block: dict[int, int] = {}
    for t in transcript:
        if t.kind == "question" and t.block_idx is not None:
            per_block[t.block_idx] = per_block.get(t.block_idx, 0) + 1
    minutes = (time.perf_counter() - t0) / 60
    printer.info(f"koniec ({final.get('phase')}), {minutes:.1f} min, pytania w blokach: {per_block}")
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(transcript_markdown(script, transcript), encoding="utf-8")
        printer.info(f"transkrypt zapisany: {out}")
    return 0 if final.get("phase") in ("done", "stopped") else 1


def cmd_run(args: argparse.Namespace) -> int:
    script = load_script(args)
    interactive = sys.stdin.isatty() and not args.no_input
    return asyncio.run(run_debate(script, get_settings(), Path(args.out) if args.out else None, interactive))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="debate", description="Debata drużyn Psy i Koty na wybrany temat")
    sub = parser.add_subparsers(dest="command", required=True)
    commands: dict[str, Callable[[argparse.Namespace], int]] = {"check": cmd_check, "run": cmd_run}
    sub.add_parser("check", help="ping prowadzącego i serwera debatantów")
    run = sub.add_parser("run", help="pełna debata w terminalu", epilog=HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = run.add_mutually_exclusive_group()
    source.add_argument("--preset", default="psy-vs-koty", choices=list_presets(), help="gotowy schemat debaty")
    source.add_argument("--script", help="własny schemat debaty (JSON zgodny z DebateScript)")
    run.add_argument("--out", help="zapisz transkrypt do pliku Markdown")
    run.add_argument("--no-input", action="store_true", help="bez komend reżysera z klawiatury")
    args = parser.parse_args(argv)
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
