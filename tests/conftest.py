import math
import struct
from pathlib import Path

import pytest

from transcriba.audio.pcm import BYTES_PER_SECOND, SAMPLE_RATE

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def tone(seconds: float, freq: float = 440.0, amp: float = 0.3) -> bytes:
    n = int(seconds * SAMPLE_RATE)
    return b"".join(struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * freq * i / SAMPLE_RATE))) for i in range(n))


def silence(seconds: float) -> bytes:
    return b"\x00" * int(seconds * BYTES_PER_SECOND)


@pytest.fixture
def speechlike():
    return silence(0.5) + tone(1.0) + silence(0.8) + tone(2.0, 330) + silence(1.0) + tone(0.2, 550) + silence(1.0)


@pytest.fixture
def jfk_pcm() -> bytes:
    import wave

    with wave.open(str(SAMPLES / "jfk.wav"), "rb") as w:
        assert w.getframerate() == SAMPLE_RATE and w.getnchannels() == 1
        return w.readframes(w.getnframes())
