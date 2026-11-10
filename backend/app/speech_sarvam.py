"""Sarvam AI streaming STT adapter (saaras:v3, codemix mode) — real-time Hindi/Hinglish
transcription over a WebSocket, not a batch-REST fallback. Input is raw PCM16-LE at
16 kHz mono (Sarvam's streaming API only accepts 8000 or 16000 Hz; this app already
runs its whole pipeline at 16 kHz, so no extra resampling is needed here — the Twilio
path converts its native 8 kHz mu-law to 16 kHz PCM before handing audio to this class,
reusing the same conversion already used for phone-audio playback).

One real difference from DeepgramStream: Sarvam's streaming API is VAD-segmented and
returns only finalized transcripts per detected speech segment — there is no partial/
interim result stream. `consume()` therefore never calls `on_interim`; every message
is treated as a final utterance. This was verified against the live API, not assumed:
see the design doc / PR description for the probe transcript.
"""
from __future__ import annotations

import base64
import logging
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack

from .config import Settings

log = logging.getLogger(__name__)
TextCallback = Callable[[str], Awaitable[None]]

MODEL = "saaras:v3"
MODE = "codemix"  # mixed Hindi/English in native script, matching this app's prompts


class SarvamStream:
    def __init__(self, settings: Settings, sample_rate: int = 16000):
        self.settings = settings
        self.sample_rate = sample_rate
        self._exit_stack: AsyncExitStack | None = None
        self._socket = None

    async def open(self) -> None:
        if not self.settings.sarvam_api_key:
            raise RuntimeError("SARVAM_API_KEY is not configured.")
        from sarvamai import AsyncSarvamAI

        client = AsyncSarvamAI(api_subscription_key=self.settings.sarvam_api_key)
        self._exit_stack = AsyncExitStack()
        self._socket = await self._exit_stack.enter_async_context(
            client.speech_to_text_streaming.connect(
                language_code=self.settings.sarvam_language,
                model=MODEL,
                mode=MODE,
                sample_rate=str(self.sample_rate),
                input_audio_codec="pcm_s16le",
            )
        )

    async def send_audio(self, data: bytes) -> None:
        if self._socket is None:
            raise RuntimeError("Sarvam stream is not connected.")
        await self._socket.transcribe(audio=base64.b64encode(data).decode("ascii"), sample_rate=self.sample_rate)

    async def finalize(self) -> None:
        if self._socket:
            await self._socket.flush()

    async def keepalive(self) -> None:
        pass  # no documented idle-timeout/keepalive message for this API

    async def close(self) -> None:
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
            self._socket = None

    async def consume(self, on_interim: TextCallback, on_final: TextCallback, on_error: TextCallback) -> None:
        if not self._socket:
            raise RuntimeError("Must open the Sarvam stream before consuming events.")
        async for message in self._socket:
            kind = getattr(message, "type", None)
            if kind == "data":
                text = (getattr(message.data, "transcript", "") or "").strip()
                if text:
                    await on_final(text)
            elif kind == "error":
                await on_error(str(message.data))
