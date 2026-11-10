import asyncio
from types import SimpleNamespace

from backend.app.config import Settings
from backend.app.speech_sarvam import SarvamStream


class FakeSarvamSocket:
    def __init__(self, messages):
        self.messages = messages
        self.sent = []
        self.flushed = False

    async def transcribe(self, audio, sample_rate):
        self.sent.append((audio, sample_rate))

    async def flush(self):
        self.flushed = True

    def __aiter__(self):
        async def generator():
            for message in self.messages:
                yield message
        return generator()


def test_sarvam_consume_treats_every_data_message_as_final():
    """Verified against the live API (see loop notes): Sarvam's streaming endpoint is
    VAD-segmented and only emits finalized transcripts, never partials — so consume()
    should call on_final for every 'data' message and never call on_interim."""
    async def run():
        messages = [
            SimpleNamespace(type="data", data=SimpleNamespace(transcript="Namaste, aapka solution")),
            SimpleNamespace(type="data", data=SimpleNamespace(transcript="thoda expensive lag raha hai")),
            SimpleNamespace(type="data", data=SimpleNamespace(transcript="")),  # empty segments are dropped
            SimpleNamespace(type="error", data="something went wrong"),
        ]
        stream = SarvamStream(Settings())
        stream._socket = FakeSarvamSocket(messages)
        interims, finals, errors = [], [], []
        await stream.consume(
            on_interim=_collector(interims),
            on_final=_collector(finals),
            on_error=_collector(errors),
        )
        assert interims == []
        assert finals == ["Namaste, aapka solution", "thoda expensive lag raha hai"]
        assert errors == ["something went wrong"]
    asyncio.run(run())


def _collector(target):
    async def _append(value):
        target.append(value)
    return _append


def test_sarvam_send_audio_base64_encodes_and_uses_configured_sample_rate():
    async def run():
        stream = SarvamStream(Settings(), sample_rate=16000)
        fake = FakeSarvamSocket([])
        stream._socket = fake
        await stream.send_audio(b"\x01\x02\x03\x04")
        assert len(fake.sent) == 1
        audio_b64, sample_rate = fake.sent[0]
        assert sample_rate == 16000
        import base64
        assert base64.b64decode(audio_b64) == b"\x01\x02\x03\x04"
    asyncio.run(run())


def test_sarvam_finalize_calls_flush():
    async def run():
        stream = SarvamStream(Settings())
        fake = FakeSarvamSocket([])
        stream._socket = fake
        await stream.finalize()
        assert fake.flushed is True
    asyncio.run(run())


def test_sarvam_open_requires_api_key():
    async def run():
        stream = SarvamStream(Settings(sarvam_api_key=""))
        try:
            await stream.open()
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "SARVAM_API_KEY" in str(exc)
    asyncio.run(run())
