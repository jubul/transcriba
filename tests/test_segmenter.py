from transcriba.audio.pcm import BYTES_PER_SECOND
from transcriba.audio.segmenter import ActivityTracker, Segmenter
from transcriba.config import VadConfig


def feed_all(seg: Segmenter, pcm: bytes, chunk: int = 3200):
    out = []
    for i in range(0, len(pcm), chunk):
        out += seg.feed(pcm[i : i + chunk])
    tail = seg.flush()
    if tail:
        out.append(tail)
    return out


def test_segments_cut_at_pauses_and_drop_blips(speechlike):
    seg = Segmenter(VadConfig(min_silence_ms=500, min_segment_s=0.5, max_segment_s=8, min_speech_ms=300))
    segs = feed_all(seg, speechlike)
    assert len(segs) == 2, [s.duration_s for s in segs]
    assert 0.9 <= segs[0].duration_s <= 2.2
    assert 1.9 <= segs[1].duration_s <= 3.2
    assert segs[0].start_s < 0.6
    assert segs[1].start_s > segs[0].end_s - 0.01
    assert all(abs(len(s.pcm) - s.duration_s * BYTES_PER_SECOND) < 2 for s in segs)


def test_max_segment_forces_cut():
    from tests.conftest import tone

    seg = Segmenter(VadConfig(min_silence_ms=500, max_segment_s=3.0, min_speech_ms=300))
    segs = feed_all(seg, tone(10.0))
    assert len(segs) >= 3
    assert all(s.duration_s <= 3.1 for s in segs)
    assert abs(sum(s.duration_s for s in segs) - 10.0) < 0.2


def test_silence_yields_nothing():
    seg = Segmenter()
    assert feed_all(seg, b"\x00" * BYTES_PER_SECOND * 5) == []


def test_activity_tracker(speechlike):
    tr = ActivityTracker()
    for i in range(0, len(speechlike), 3200):
        tr.feed(speechlike[i : i + 3200])
    assert tr.quiet_ms >= 900
    tr.feed(speechlike[int(0.6 * BYTES_PER_SECOND) : int(0.7 * BYTES_PER_SECOND)])
    assert tr.quiet_ms == 0
