"""Lifespan-owned background worker.

Two jobs, both deliberately *not* tied to a WebSocket connection's lifetime:
1. Post-call processing (summary + CRM/WhatsApp/webhook distribution) enqueued when
   a call closes — retried by the queue semantics, not silently lost if the socket
   task is mid-teardown.
2. A periodic tick: due webhook delivery retries and retention pruning.

The worker task is created in FastAPI lifespan startup and drained gracefully on
shutdown, so TestClient and real ASGI servers behave identically.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class BackgroundWorker:
    def __init__(
        self,
        call_handler: Callable[[str], Awaitable[None]],
        tick_handler: Callable[[], Awaitable[None]],
        tick_seconds: float = 10.0,
    ):
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._call_handler = call_handler
        self._tick_handler = tick_handler
        self._tick_seconds = tick_seconds
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="copilot-worker")

    def enqueue_call(self, call_id: str) -> None:
        if call_id:
            self.queue.put_nowait(call_id)

    async def _run(self) -> None:
        while True:
            try:
                call_id = await asyncio.wait_for(self.queue.get(), timeout=self._tick_seconds)
            except asyncio.TimeoutError:
                call_id = None
            try:
                if call_id:
                    await self._call_handler(call_id)
                await self._tick_handler()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Background worker iteration failed")

    async def drain(self, timeout: float = 3.0) -> None:
        """Process everything already queued (best effort, bounded), used at shutdown."""
        if self._task is None:
            return
        deadline = asyncio.get_event_loop().time() + timeout
        while not self.queue.empty():
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                call_id = await asyncio.wait_for(self.queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            try:
                await self._call_handler(call_id)
            except Exception:
                logger.exception("Worker drain failed for call %s", call_id)

    async def stop(self) -> None:
        await self.drain()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
