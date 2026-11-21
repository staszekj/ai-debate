"""Pause, resume and stop controls for a debate."""

from __future__ import annotations

import asyncio

class DirectorChannel:
    def __init__(self) -> None:
        self._running = asyncio.Event()
        self._running.set()
        self._stopped = False

    @property
    def paused(self) -> bool:
        return not self._running.is_set()

    @property
    def stopped(self) -> bool:
        return self._stopped

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def stop(self) -> None:
        self._stopped = True
        self._running.set()  # odblokuj czekający checkpoint, żeby graf mógł się zakończyć

    async def checkpoint(self) -> bool:
        await self._running.wait()
        return self._stopped
