import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from google.genai import types

from transcriba.audio.pcm import silence
from transcriba.config import GeminiLiveConfig
from transcriba.engines.base import EngineContext
from transcriba.engines.gemini_live import GeminiLiveEngine
from transcriba.models import CaptionStatus
from transcriba.translators.mock import MockTranslator

CLOSE = object()


class FakeSession:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.inbox: asyncio.Queue = asyncio.Queue()

    async def send_realtime_input(self, **kw) -> None:
        self.sent.append(kw)

    async def receive(self):
        while True:
            item = await self.inbox.get()
            if item is CLOSE:
                raise ConnectionError("server closed")
            yield item

    @property
    def audio_chunks(self) -> int:
        return sum(1 for s in self.sent if "audio" in s)

    @property
    def ended(self) -> bool:
        return any(s.get("audio_stream_end") for s in self.sent)


class FakeLive:
    def __init__(self) -> None:
        self.sessions: list[FakeSession] = []

    @asynccontextmanager
    async def connect(self, *, model, config):
        assert isinstance(config, types.LiveConnectConfig)
        s = FakeSession()
        self.sessions.append(s)
        yield s


def make_engine(emitted, **cfg):
    async def emit(cap):
        emitted.append(cap.model_copy(deep=True))

    ctx = EngineContext("s1", "en", ["es"], [], {}, emit=emit, clock=lambda: 1.0)
    fake = FakeLive()
    client = SimpleNamespace(aio=SimpleNamespace(live=fake))
    eng = GeminiLiveEngine(ctx, MockTranslator(), GeminiLiveConfig(reconnect_backoff_s=0.05, **cfg), client)
    return eng, fake


def final_msg(text, finished=True):
    return types.LiveServerMessage(
        server_content=types.LiveServerContent(input_transcription=types.Transcription(text=text, finished=finished))
    )


async def test_stop_flushes_audio_signals_end_and_drains_finals():
    emitted = []
    eng, fake = make_engine(emitted, drain_timeout_s=1.0)
    await eng.start()
    for _ in range(3):
        await eng.feed(silence(100))
    await asyncio.sleep(0.15)
    session = fake.sessions[0]
    assert session.audio_chunks == 3

    async def server_side():
        while not session.ended:
            await asyncio.sleep(0.01)
        await session.inbox.put(final_msg("Ask what you can do for your country."))

    asyncio.create_task(server_side())
    await eng.feed(silence(100))
    await eng.stop()
    assert session.ended and session.audio_chunks == 4
    assert [c.status for c in emitted] == [CaptionStatus.final, CaptionStatus.translated]
    assert emitted[0].original == "Ask what you can do for your country."
    assert eng.info["state"] == "stopped"


async def test_rotation_opens_new_sessions_and_ends_old_ones():
    emitted = []
    eng, fake = make_engine(emitted, rotate_after_s=0.15, rotate_deadline_s=0.3, rotate_quiet_ms=50, drain_timeout_s=0.05)
    await eng.start()
    for _ in range(12):
        await eng.feed(silence(100))
        await asyncio.sleep(0.05)
    await eng.stop()
    assert len(fake.sessions) >= 2, fake.sessions
    assert all(s.ended for s in fake.sessions)
    assert eng.info["rotations"] >= 1 and eng.info["reconnects"] == 0
    assert sum(s.audio_chunks for s in fake.sessions) == 12


async def test_reconnects_after_server_closes():
    emitted = []
    eng, fake = make_engine(emitted, drain_timeout_s=0.05)
    await eng.start()
    await eng.feed(silence(100))
    await asyncio.sleep(0.2)
    assert len(fake.sessions) == 1 and fake.sessions[0].audio_chunks == 1
    await fake.sessions[0].inbox.put(CLOSE)
    await asyncio.sleep(0.3)
    assert eng.info["reconnects"] == 1 and "ConnectionError" in eng.info["last_error"]
    assert len(fake.sessions) == 1
    await eng.feed(silence(100))
    await asyncio.sleep(0.3)
    assert len(fake.sessions) == 2 and fake.sessions[1].audio_chunks == 1
    await eng.stop()


async def test_connects_lazily_and_closes_when_idle():
    emitted = []
    eng, fake = make_engine(emitted, idle_close_s=0.3, drain_timeout_s=0.05)
    await eng.start()
    await asyncio.sleep(0.2)
    assert fake.sessions == []
    assert "waiting for audio" in eng.info["state"]
    await eng.feed(silence(100))
    await asyncio.sleep(0.15)
    assert len(fake.sessions) == 1 and fake.sessions[0].audio_chunks == 1
    await asyncio.sleep(0.6)
    assert fake.sessions[0].ended and eng.info["idle_closes"] == 1 and eng.info["reconnects"] == 0
    await eng.feed(silence(100))
    await asyncio.sleep(0.2)
    assert len(fake.sessions) == 2 and fake.sessions[1].audio_chunks == 1
    await eng.stop()


async def test_mid_sentence_pieces_wait_for_the_rest():
    emitted = []
    eng, _ = make_engine(emitted, final_chunk_timeout_s=0.05, final_chunk_max_wait_s=0.5)
    await eng.handle_message(final_msg("And so, my fellow Americans, ask not what your country can", finished=False))
    await asyncio.sleep(0.1)
    assert all(c.status == CaptionStatus.partial for c in emitted)
    await eng.handle_message(final_msg("do for you.", finished=True))
    await eng.stop()
    finals = [c for c in emitted if c.status == CaptionStatus.final]
    assert len(finals) == 1
    assert finals[0].original == "And so, my fellow Americans, ask not what your country can do for you."


async def test_unsignalled_final_ending_a_sentence_commits_immediately():
    emitted = []
    eng, _ = make_engine(emitted, final_chunk_max_wait_s=5.0)
    await eng.handle_message(final_msg("Short and complete.", finished=None))
    assert emitted[-1].status == CaptionStatus.final
    await eng.stop()
