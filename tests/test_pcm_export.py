import io
import wave

from transcriba.audio.pcm import pcm_to_wav, resample_pcm, rms_dbfs
from transcriba.export import to_srt, to_txt, to_vtt
from transcriba.models import Caption, CaptionStatus


def test_wav_roundtrip():
    pcm = b"\x01\x00" * 1600
    wav = pcm_to_wav(pcm)
    with wave.open(io.BytesIO(wav), "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        assert w.readframes(w.getnframes()) == pcm


def test_resample_halves_length():
    pcm = b"\x00\x10" * 4800
    out = resample_pcm(pcm, 48000, 16000)
    assert len(out) == 3200
    assert abs(rms_dbfs(out) - rms_dbfs(pcm)) < 0.5


def caps():
    return [
        Caption(
            id="s-1",
            session_id="s",
            seq=1,
            status=CaptionStatus.translated,
            original="Hello there",
            language="en",
            translations={"es": "Hola"},
            t_start=1.0,
            t_end=2.5,
        ),
        Caption(id="s-2", session_id="s", seq=2, status=CaptionStatus.partial, original="partial", t_start=2.6),
        Caption(
            id="s-3",
            session_id="s",
            seq=3,
            status=CaptionStatus.translated,
            original="Second one",
            language="en",
            translations={"es": "Segunda"},
            t_start=3.0,
        ),
    ]


def test_srt_vtt_txt():
    srt = to_srt(caps(), "es")
    assert "1\n00:00:01,000 --> 00:00:02,500\nHola\n" in srt
    assert "partial" not in srt
    assert "Segunda" in srt
    vtt = to_vtt(caps(), "both")
    assert vtt.startswith("WEBVTT") and "Hello there\nHola" in vtt
    txt = to_txt(caps(), "orig")
    assert "[00:00:01] Hello there" in txt
