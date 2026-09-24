from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from transcriba.audio.pcm import BYTES_PER_SECOND, rms_dbfs
from transcriba.config import VadConfig


@dataclass
class Segment:
    pcm: bytes
    start_s: float
    end_s: float
    speech_ms: int = 0

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass
class _Frame:
    pcm: bytes
    start_s: float
    speech: bool


@dataclass
class Segmenter:
    cfg: VadConfig = field(default_factory=VadConfig)

    def __post_init__(self) -> None:
        self.frame_bytes = BYTES_PER_SECOND * self.cfg.frame_ms // 1000
        self._pending = bytearray()
        self._pos_bytes = 0
        self._pre_roll: deque[_Frame] = deque(maxlen=max(1, self.cfg.pre_roll_ms // self.cfg.frame_ms))
        self._frames: list[_Frame] = []
        self._silence_ms = 0
        self._noise_floor = -60.0
        self._last_level = -100.0

    @property
    def in_speech(self) -> bool:
        return bool(self._frames) and self._silence_ms < self.cfg.min_silence_ms

    @property
    def noise_floor_dbfs(self) -> float:
        return self._noise_floor

    @property
    def level_dbfs(self) -> float:
        return self._last_level

    def feed(self, pcm: bytes) -> list[Segment]:
        out: list[Segment] = []
        self._pending.extend(pcm)
        while len(self._pending) >= self.frame_bytes:
            frame = bytes(self._pending[: self.frame_bytes])
            del self._pending[: self.frame_bytes]
            start_s = self._pos_bytes / BYTES_PER_SECOND
            self._pos_bytes += self.frame_bytes
            seg = self._process_frame(frame, start_s)
            if seg is not None:
                out.append(seg)
        return out

    def flush(self) -> Segment | None:
        seg = self._close(self._frames)
        self._frames = []
        self._silence_ms = 0
        return seg

    def _is_speech(self, level: float) -> bool:
        return level > max(self._noise_floor + self.cfg.speech_threshold_db, self.cfg.min_speech_dbfs)

    def _process_frame(self, frame: bytes, start_s: float) -> Segment | None:
        level = rms_dbfs(frame)
        self._last_level = level
        speech = self._is_speech(level)
        if not speech and level > -100.0:
            self._noise_floor = min(-20.0, self._noise_floor * 0.95 + level * 0.05)
        f = _Frame(frame, start_s, speech)

        if not self._frames:
            if speech:
                self._frames = [*self._pre_roll, f]
                self._pre_roll.clear()
                self._silence_ms = 0
            else:
                self._pre_roll.append(f)
            return None

        self._frames.append(f)
        self._silence_ms = 0 if speech else self._silence_ms + self.cfg.frame_ms
        dur_s = len(self._frames) * self.cfg.frame_ms / 1000.0

        if self._silence_ms >= self.cfg.min_silence_ms and dur_s >= self.cfg.min_segment_s:
            seg = self._close(self._frames)
            self._frames = []
            self._silence_ms = 0
            return seg

        if dur_s >= self.cfg.max_segment_s:
            return self._force_cut()
        return None

    def _force_cut(self) -> Segment | None:
        lookback = int(2000 / self.cfg.frame_ms)
        cut = len(self._frames)
        for i in range(len(self._frames) - 1, max(0, len(self._frames) - lookback) - 1, -1):
            if not self._frames[i].speech:
                cut = i + 1
                break
        head, tail = self._frames[:cut], self._frames[cut:]
        seg = self._close(head)
        self._frames = tail
        self._silence_ms = 0
        return seg

    def _close(self, frames: list[_Frame]) -> Segment | None:
        if not frames:
            return None
        speech_ms = sum(self.cfg.frame_ms for f in frames if f.speech)
        if speech_ms < self.cfg.min_speech_ms:
            return None
        pcm = b"".join(f.pcm for f in frames)
        start = frames[0].start_s
        return Segment(pcm=pcm, start_s=start, end_s=start + len(pcm) / BYTES_PER_SECOND, speech_ms=speech_ms)


class ActivityTracker:
    def __init__(self, threshold_db: float = 10.0, min_speech_dbfs: float = -55.0) -> None:
        self.threshold_db = threshold_db
        self.min_speech_dbfs = min_speech_dbfs
        self.noise_floor = -60.0
        self.quiet_ms = 10_000
        self.level = -100.0

    def feed(self, pcm: bytes) -> None:
        level = rms_dbfs(pcm)
        self.level = level
        ms = int(1000 * len(pcm) / BYTES_PER_SECOND)
        speech = level > max(self.noise_floor + self.threshold_db, self.min_speech_dbfs)
        if speech:
            self.quiet_ms = 0
        else:
            self.quiet_ms += ms
            if level > -100.0:
                self.noise_floor = min(-20.0, self.noise_floor * 0.95 + level * 0.05)
