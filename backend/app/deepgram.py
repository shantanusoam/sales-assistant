"""Deepgram Listen v1 streaming adapter. Input is raw PCM16-LE at 16 kHz mono."""
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect

from .config import Settings

log = logging.getLogger(__name__)
TextCallback = Callable[[str], Awaitable[None]]


class DeepgramStream:
    def __init__(self, settings: Settings, encoding: str = "linear16", sample_rate: int = 16000):
        self.settings = settings
        self.encoding = encoding
        self.sample_rate = sample_rate
        self.socket: ClientConnection | None = None
        self.final_parts: list[str] = []

    async def open(self) -> None:
        if not self.settings.deepgram_api_key:
            raise RuntimeError("DEEPGRAM_API_KEY is not configured.")
        query = urlencode({
            "model": self.settings.deepgram_model,
            "language": self.settings.deepgram_language,
            "encoding": self.encoding,
            "sample_rate": self.sample_rate,
            "channels": 1,
            "interim_results": "true",
            "punctuate": "true",
            "smart_format": "true",
            "endpointing": 300,
            "vad_events": "true",
            "utterance_end_ms": 1000,
        })
        self.socket = await connect(
            f"wss://api.deepgram.com/v1/listen?{query}",
            additional_headers={"Authorization": f"Token {self.settings.deepgram_api_key}"},
            max_size=2_000_000,
            open_timeout=8,
            ping_interval=20,
        )

    async def send_audio(self, data: bytes) -> None:
        if self.socket is None:
            raise RuntimeError("Deepgram stream is not connected.")
        await self.socket.send(data)

    async def finalize(self) -> None:
        if self.socket:
            await self.socket.send(json.dumps({"type": "Finalize"}))

    async def keepalive(self) -> None:
        if self.socket:
            await self.socket.send(json.dumps({"type": "KeepAlive"}))

    async def close(self) -> None:
        if self.socket:
            try:
                await self.socket.send(json.dumps({"type": "CloseStream"}))
            except Exception:
                pass
            await self.socket.close()
            self.socket = None

    async def consume(self, on_interim: TextCallback, on_final: TextCallback, on_error: TextCallback) -> None:
        if not self.socket:
            raise RuntimeError("Must open Deepgram before consuming events.")
        async for raw in self.socket:
            try:
                event = json.loads(raw)
            except (TypeError, ValueError):
                continue
            kind = event.get("type")
            if kind == "Results":
                alternatives = event.get("channel", {}).get("alternatives") or []
                transcript = (alternatives[0].get("transcript") or "").strip() if alternatives else ""
                if event.get("is_final") and transcript:
                    self.final_parts.append(transcript)
                elif transcript:
                    await on_interim(transcript)
                if event.get("speech_final"):
                    await self._finish(on_final)
            elif kind == "UtteranceEnd":
                await self._finish(on_final)
            elif kind == "Error":
                await on_error(event.get("description") or "Deepgram reported an error.")

    async def _finish(self, on_final: TextCallback) -> None:
        text = " ".join(self.final_parts).strip()
        self.final_parts.clear()
        if text:
            await on_final(text)
