"""`DirectorChannel`: kolejka komend reżysera i pauza.

Reżyser (CLI albo WebSocket) wysyła komendy w dowolnym momencie. Graf odbiera je
w `director_gate`, czyli w punkcie kontrolnym przed każdą wypowiedzią:
`checkpoint()` czeka, dopóki debata jest wstrzymana, a potem oddaje zaległe komendy.
"""

from __future__ import annotations

import asyncio

from debate_core.state import ExtraQuestion, Note, Reprimand

Command = Reprimand | ExtraQuestion | Note


class DirectorChannel:
    def __init__(self) -> None:
        self._queue: list[Command] = []
        self._running = asyncio.Event()
        self._running.set()
        self._stopped = False

    @property
    def paused(self) -> bool:
        return not self._running.is_set()

    @property
    def stopped(self) -> bool:
        return self._stopped

    def send(self, command: Command) -> str:
        """Dodaje komendę do kolejki i zwraca jej id (do potwierdzeń `director_ack`)."""
        self._queue.append(command)
        return command.id

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def stop(self) -> None:
        self._stopped = True
        self._running.set()  # odblokuj czekający checkpoint, żeby graf mógł się zakończyć

    async def checkpoint(self) -> tuple[list[Command], bool]:
        """Czeka na wznowienie, zwraca (zaległe komendy, czy zatrzymano)."""
        await self._running.wait()
        if self._stopped:
            return [], True
        commands, self._queue = self._queue, []
        return commands, False
