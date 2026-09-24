from __future__ import annotations

import asyncio
import logging
import os
import shlex
import shutil
from abc import ABC, abstractmethod
from typing import AsyncIterator

from transcriba.audio.pcm import CHUNK_BYTES, SAMPLE_RATE

log = logging.getLogger(__name__)

STREAM_SCHEMES = ("rtmp://", "rtmps://", "srt://", "rtsp://", "udp://", "tcp://", "http://", "https://", "hls://")
DEVICE_FORMATS = {"pulse", "alsa", "avfoundation", "dshow", "openal", "jack", "sndio", "oss"}


class AudioSource(ABC):
    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    def __aiter__(self) -> AsyncIterator[bytes]: ...

    @property
    def description(self) -> str:
        return type(self).__name__


def build_ffmpeg_args(spec: str, extra_args: list[str] | None = None, loop: bool = False, realtime: bool = True) -> list[str]:
    extra_args = list(extra_args or [])
    args: list[str] = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin"]
    input_args: list[str]

    if spec.startswith("ffmpeg:"):
        input_args = shlex.split(spec[len("ffmpeg:") :])
    elif spec.startswith(STREAM_SCHEMES):
        input_args = ["-i", spec]
        if spec.startswith(("rtmp://", "rtmps://", "rtsp://", "srt://")):
            input_args = ["-fflags", "nobuffer", "-flags", "low_delay", *input_args]
    else:
        fmt, _, dev = spec.partition(":")
        if fmt in DEVICE_FORMATS:
            input_args = ["-f", fmt, "-i", dev or "default"]
        else:
            path = spec[len("file:") :] if spec.startswith("file:") else spec
            input_args = []
            if realtime:
                input_args.append("-re")
            if loop:
                input_args += ["-stream_loop", "-1"]
            input_args += ["-i", path]

    args += extra_args + input_args
    args += ["-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1"]
    return args


class FfmpegSource(AudioSource):
    def __init__(
        self,
        spec: str,
        extra_args: list[str] | None = None,
        *,
        loop: bool = False,
        realtime: bool = True,
        restart: bool = True,
        chunk_bytes: int = CHUNK_BYTES,
    ) -> None:
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg not found in PATH; install it (apt install ffmpeg / brew install ffmpeg)")
        self.spec = spec
        self.args = build_ffmpeg_args(spec, extra_args, loop=loop, realtime=realtime)
        self.restart = restart and (spec.startswith(STREAM_SCHEMES) or spec.split(":")[0] in DEVICE_FORMATS)
        self.chunk_bytes = chunk_bytes
        self._proc: asyncio.subprocess.Process | None = None
        self._stopping = False
        self._stderr_task: asyncio.Task | None = None
        self.last_error: str = ""

    @property
    def description(self) -> str:
        return f"ffmpeg:{self.spec}"

    async def start(self) -> None:
        self._stopping = False
        await self._spawn()

    async def _spawn(self) -> None:
        log.info("spawning: %s", " ".join(shlex.quote(a) for a in self.args))
        self._proc = await asyncio.create_subprocess_exec(
            *self.args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )
        self._stderr_task = asyncio.create_task(self._pump_stderr(self._proc))

    async def _pump_stderr(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stderr is not None
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip()
                if text and "Guessed Channel Layout" not in text:
                    self.last_error = text
                    log.warning("ffmpeg[%s]: %s", self.spec, text)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        self._stopping = True
        proc, self._proc = self._proc, None
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                proc.kill()
        if self._stderr_task:
            self._stderr_task.cancel()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        backoff = 1.0
        while not self._stopping:
            proc = self._proc
            if proc is None or proc.stdout is None:
                return
            try:
                chunk = await proc.stdout.readexactly(self.chunk_bytes)
                backoff = 1.0
                yield chunk
                continue
            except asyncio.IncompleteReadError as e:
                if e.partial:
                    yield e.partial
            rc = await proc.wait()
            if self._stopping:
                return
            if not self.restart:
                log.info("ffmpeg[%s] ended (rc=%s)", self.spec, rc)
                return
            log.warning("ffmpeg[%s] exited rc=%s; restarting in %.1fs", self.spec, rc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 15.0)
            if self._stderr_task:
                self._stderr_task.cancel()
            await self._spawn()


class PushSource(AudioSource):
    def __init__(self, maxsize: int = 300) -> None:
        self._q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=maxsize)
        self._closed = False
        self.connected = False
        self.dropped = 0

    @property
    def description(self) -> str:
        return "browser"

    async def start(self) -> None:
        self._closed = False

    async def stop(self) -> None:
        self._closed = True
        try:
            self._q.put_nowait(None)
        except asyncio.QueueFull:
            pass

    def push(self, pcm: bytes) -> None:
        if self._closed:
            return
        try:
            self._q.put_nowait(pcm)
        except asyncio.QueueFull:
            try:
                self._q.get_nowait()
                self.dropped += 1
            except asyncio.QueueEmpty:
                pass
            self._q.put_nowait(pcm)

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while True:
            item = await self._q.get()
            if item is None:
                return
            yield item


def make_source(spec: str, extra_args: list[str] | None = None, *, loop: bool = False, realtime: bool = True) -> AudioSource:
    if spec in ("browser", "push", "ws"):
        return PushSource()
    return FfmpegSource(spec, extra_args, loop=loop, realtime=realtime)


def looks_like_file(spec: str) -> bool:
    if spec.startswith("file:"):
        return True
    if spec.startswith(STREAM_SCHEMES) or spec.startswith("ffmpeg:") or spec in ("browser", "push", "ws"):
        return False
    return spec.split(":")[0] not in DEVICE_FORMATS and os.path.exists(spec)
