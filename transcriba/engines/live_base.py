from __future__ import annotations

import asyncio
import logging
import re
import time
from abc import abstractmethod
from contextlib import suppress

from google import genai
from google.genai import types

from transcriba.audio.segmenter import ActivityTracker
from transcriba.config import LiveSessionConfig
from transcriba.engines.base import Engine, EngineContext
from transcriba.translators.base import Translator

log = logging.getLogger(__name__)

PCM_MIME = "audio/pcm;rate=16000"


async def reap(task: asyncio.Task) -> BaseException | None:
    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        cur = asyncio.current_task()
        if cur is not None and getattr(cur, "cancelling", lambda: 0)():
            raise
        return None
    except Exception as e:
        return e
    return None


def parse_duration_s(value: object, default: float = 5.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    m = re.match(r"^\s*([0-9.]+)\s*s?\s*$", str(value))
    return float(m.group(1)) if m else default


class LiveSessionEngine(Engine):
    name = "live"

    def __init__(
        self,
        ctx: EngineContext,
        translator: Translator | None,
        live_cfg: LiveSessionConfig,
        client: genai.Client,
        model: str,
    ) -> None:
        super().__init__(ctx, translator)
        self.live_cfg = live_cfg
        self.client = client
        self.model = model
        self._audio_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=600)
        self._tracker = ActivityTracker()
        self._runner: asyncio.Task | None = None
        self._stopping = False
        self._stop_event = asyncio.Event()
        self._rotate_request = False
        self._go_away_deadline: float | None = None
        self.info.update(
            {
                "model": model,
                "state": "idle",
                "sessions": 0,
                "rotations": 0,
                "reconnects": 0,
                "idle_closes": 0,
                "dropped_chunks": 0,
                "last_error": None,
            }
        )

    @abstractmethod
    def build_config(self) -> types.LiveConnectConfig: ...

    @abstractmethod
    async def handle_message(self, msg: types.LiveServerMessage) -> None: ...

    async def on_session_end(self) -> None:
        return None

    async def start(self) -> None:
        self._stopping = False
        self._stop_event = asyncio.Event()
        self._runner = asyncio.create_task(self._run(), name=f"live:{self.ctx.session_id}")

    async def feed(self, pcm: bytes) -> None:
        self._tracker.feed(pcm)
        try:
            self._audio_q.put_nowait(pcm)
        except asyncio.QueueFull:
            with suppress(asyncio.QueueEmpty):
                self._audio_q.get_nowait()
            self.info["dropped_chunks"] += 1
            self._audio_q.put_nowait(pcm)

    async def stop(self) -> None:
        self._stopping = True
        self._stop_event.set()
        if self._runner is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._runner), timeout=self.live_cfg.drain_timeout_s + 5.0)
            except asyncio.TimeoutError:
                log.warning("[%s] live engine did not stop gracefully; cancelling", self.ctx.session_id)
                await reap(self._runner)
            except Exception:
                pass
            self._runner = None
        await super().stop()
        self.info["state"] = "stopped"

    async def _wait_for_audio(self) -> bool:
        self.info["state"] = "idle (waiting for audio)"
        while not self._stopping:
            if not self._audio_q.empty():
                return True
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=0.1)
        return False

    async def _run(self) -> None:
        backoff = self.live_cfg.reconnect_backoff_s
        while not self._stopping:
            if not await self._wait_for_audio():
                break
            try:
                await self._run_one_session()
                backoff = self.live_cfg.reconnect_backoff_s
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if self._stopping:
                    break
                self.info["reconnects"] += 1
                self.info["last_error"] = f"{type(e).__name__}: {e}"[:300]
                self.info["state"] = "reconnecting"
                log.warning("[%s] live session error: %s; reconnecting in %.1fs", self.ctx.session_id, e, backoff)
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                backoff = min(backoff * 2, self.live_cfg.reconnect_backoff_max_s)

    async def _run_one_session(self) -> None:
        self.info["sessions"] += 1
        self.info["state"] = "connecting"
        self._rotate_request = False
        self._go_away_deadline = None
        recv_exc: BaseException | None = None
        async with self.client.aio.live.connect(model=self.model, config=self.build_config()) as session:
            self.info["state"] = "streaming"
            started = time.monotonic()
            recv = asyncio.create_task(self._receive_loop(session), name=f"live-recv:{self.ctx.session_id}")
            try:
                await self._send_loop(session, started, recv)
                if not recv.done():
                    with suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(asyncio.shield(recv), timeout=self.live_cfg.drain_timeout_s)
            finally:
                recv_exc = await reap(recv)
                with suppress(Exception):
                    await self.on_session_end()
        if recv_exc is not None and not self._stopping:
            raise recv_exc

    def _should_rotate(self, elapsed: float) -> bool:
        cfg = self.live_cfg
        if elapsed >= cfg.rotate_deadline_s:
            return True
        if self._go_away_deadline is not None and time.monotonic() >= self._go_away_deadline - 1.0:
            return True
        wanted = self._rotate_request or elapsed >= cfg.rotate_after_s
        return wanted and self._tracker.quiet_ms >= cfg.rotate_quiet_ms

    async def _send_chunk(self, session, chunk: bytes) -> None:
        await session.send_realtime_input(audio=types.Blob(data=chunk, mime_type=PCM_MIME))

    async def _send_loop(self, session, started: float, recv: asyncio.Task) -> None:
        last_audio = time.monotonic()
        while not self._stopping:
            if recv.done():
                return
            elapsed = time.monotonic() - started
            if self._should_rotate(elapsed):
                log.info("[%s] rotating live session after %.0fs (quiet %d ms)", self.ctx.session_id, elapsed, self._tracker.quiet_ms)
                self.info["rotations"] += 1
                with suppress(Exception):
                    await session.send_realtime_input(audio_stream_end=True)
                return
            try:
                chunk = await asyncio.wait_for(self._audio_q.get(), timeout=0.25)
            except asyncio.TimeoutError:
                if time.monotonic() - last_audio >= self.live_cfg.idle_close_s:
                    log.info(
                        "[%s] no audio for %.0fs; closing live session until audio resumes", self.ctx.session_id, self.live_cfg.idle_close_s
                    )
                    self.info["idle_closes"] += 1
                    with suppress(Exception):
                        await session.send_realtime_input(audio_stream_end=True)
                    return
                continue
            last_audio = time.monotonic()
            await self._send_chunk(session, chunk)
        if recv.done():
            return
        with suppress(Exception):
            sent = 0
            while not self._audio_q.empty() and sent < 300:
                await self._send_chunk(session, self._audio_q.get_nowait())
                sent += 1
            await session.send_realtime_input(audio_stream_end=True)

    async def _receive_loop(self, session) -> None:
        empty_rounds = 0
        while True:
            got = False
            async for msg in session.receive():
                got = True
                if msg.go_away is not None:
                    left = parse_duration_s(getattr(msg.go_away, "time_left", None))
                    log.info("[%s] server go_away, %.0fs left; rotating", self.ctx.session_id, left)
                    self._rotate_request = True
                    self._go_away_deadline = time.monotonic() + left
                try:
                    await self.handle_message(msg)
                except Exception:
                    log.exception("[%s] error handling live message", self.ctx.session_id)
            if got:
                empty_rounds = 0
                continue
            empty_rounds += 1
            if empty_rounds >= 3:
                raise ConnectionError("live session closed by server")
            await asyncio.sleep(0.05)
