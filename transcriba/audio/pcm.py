from __future__ import annotations

import io
import math
import wave

import numpy as np

SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2
CHANNELS = 1
BYTES_PER_SECOND = SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS
CHUNK_MS = 100
CHUNK_BYTES = BYTES_PER_SECOND * CHUNK_MS // 1000


def pcm_to_np(pcm: bytes) -> np.ndarray:
    n = len(pcm) - (len(pcm) % SAMPLE_WIDTH)
    return np.frombuffer(pcm[:n], dtype="<i2")


def pcm_to_float32(pcm: bytes) -> np.ndarray:
    return pcm_to_np(pcm).astype(np.float32) / 32768.0


def rms_dbfs(pcm: bytes) -> float:
    x = pcm_to_np(pcm)
    if x.size == 0:
        return -100.0
    rms = math.sqrt(float(np.mean(x.astype(np.float64) ** 2)))
    if rms < 1e-9:
        return -100.0
    return max(-100.0, 20.0 * math.log10(rms / 32768.0))


def duration_s(pcm: bytes) -> float:
    return len(pcm) / BYTES_PER_SECOND


def pcm_to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def resample_pcm(pcm: bytes, src_rate: int, dst_rate: int = SAMPLE_RATE) -> bytes:
    if src_rate == dst_rate:
        return pcm
    x = pcm_to_np(pcm).astype(np.float32)
    if x.size == 0:
        return b""
    n_out = int(round(x.size * dst_rate / src_rate))
    src_idx = np.linspace(0, x.size - 1, num=n_out, dtype=np.float64)
    y = np.interp(src_idx, np.arange(x.size), x)
    return np.clip(np.round(y), -32768, 32767).astype("<i2").tobytes()


def silence(ms: int) -> bytes:
    return b"\x00" * (BYTES_PER_SECOND * ms // 1000)
