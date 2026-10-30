import asyncio
import json

from backend.app.config import Settings
from backend.app.deepgram import DeepgramStream


class FakeSocket:
    def __init__(self, events):
        self.events = events
        self.sent = []
        self.closed = False

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        self.closed = True

    def __aiter__(self):
        async def event_generator():
            for event in self.events:
                yield json.dumps(event)
        return event_generator()


def test_deepgram_finalized_utterance_only_once():
    async def run():
        events = [
            {"type":"Results", "is_final":False, "speech_final":False,
             "channel":{"alternatives":[{"transcript":"we are"}]}},
            {"type":"Results", "is_final":True, "speech_final":False,
             "channel":{"alternatives":[{"transcript":"we are using"}]}},
            {"type":"Results", "is_final":True, "speech_final":True,
             "channel":{"alternatives":[{"transcript":"spreadsheets"}]}},
            {"type":"UtteranceEnd"},
        ]
        stream = DeepgramStream(Settings())
        stream.socket = FakeSocket(events)
        interims, final, errors = [], [], []
        async def interim(s): interims.append(s)
        async def finished(s): final.append(s)
        async def error(s): errors.append(s)
        await stream.consume(interim, finished, error)
        assert interims == ["we are"]
        assert final == ["we are using spreadsheets"]
        assert errors == []
    asyncio.run(run())
