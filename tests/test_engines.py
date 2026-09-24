import asyncio

from google import genai
from google.genai import types

from transcriba.config import GeminiLiveConfig
from transcriba.engines.base import EngineContext
from transcriba.engines.gemini_live import GeminiLiveEngine, to_bcp47
from transcriba.engines.live_base import parse_duration_s
from transcriba.engines.mock import MockEngine
from transcriba.models import CaptionStatus
from transcriba.translators.mock import MockTranslator


def make_ctx(emitted, source="en", targets=("es",)):
    async def emit(cap):
        emitted.append(cap.model_copy(deep=True))

    return EngineContext("s1", source, list(targets), ["Nerdearla"], {}, emit=emit, clock=lambda: 12.5)


def live_engine(emitted, cfg=None, **ctx_kw):
    return GeminiLiveEngine(make_ctx(emitted, **ctx_kw), MockTranslator(), cfg or GeminiLiveConfig(), genai.Client(api_key="x"))


def msg(interim=None, final=None, finished=None, lang=None, go_away=None):
    sc = types.LiveServerContent(
        interim_input_transcription=types.Transcription(text=interim) if interim else None,
        input_transcription=types.Transcription(text=final, finished=finished, language_code=lang) if final else None,
    )
    return types.LiveServerMessage(server_content=sc, go_away=types.LiveServerGoAway(time_left=go_away) if go_away else None)


async def test_interim_then_final_then_translation():
    emitted = []
    eng = live_engine(emitted)
    await eng.handle_message(msg(interim="Welcome to"))
    await eng.handle_message(msg(interim="Welcome to Nerdearla"))
    await eng.handle_message(msg(final="Welcome to Nerdearla.", lang="en-US"))
    await eng.stop()
    statuses = [c.status for c in emitted]
    assert statuses == [CaptionStatus.partial, CaptionStatus.partial, CaptionStatus.final, CaptionStatus.translated]
    assert emitted[2].original == "Welcome to Nerdearla." and emitted[2].language == "en" and emitted[2].t_start == 12.5
    assert emitted[3].translations == {"es": "[es] Welcome to Nerdearla."}
    assert all(c.id == emitted[0].id for c in emitted)


async def test_unfinished_chunks_accumulate_and_flush_on_timeout():
    emitted = []
    eng = live_engine(emitted, GeminiLiveConfig(final_chunk_timeout_s=0.05))
    await eng.handle_message(msg(final="First part", finished=False))
    await eng.handle_message(msg(final="second part.", finished=False))
    assert emitted[-1].status == CaptionStatus.partial and emitted[-1].original == "First part second part."
    await asyncio.sleep(0.15)
    await eng.stop()
    finals = [c for c in emitted if c.status == CaptionStatus.final]
    assert len(finals) == 1 and finals[0].original == "First part second part."


async def test_interim_containing_committed_prefix_is_not_duplicated():
    emitted = []
    eng = live_engine(emitted)
    await eng.handle_message(msg(final="We choose to go", finished=False))
    await eng.handle_message(msg(interim="We choose to go to the moon"))
    assert emitted[-1].original == "We choose to go to the moon"
    await eng.handle_message(msg(interim="in this decade"))
    assert emitted[-1].original == "We choose to go in this decade"
    await eng.stop()


async def test_session_end_flushes_open_partial():
    emitted = []
    eng = live_engine(emitted)
    await eng.handle_message(msg(interim="Unfinished thought"))
    await eng.on_session_end()
    await eng.stop()
    assert [c.status for c in emitted][-2:] == [CaptionStatus.final, CaptionStatus.translated]


async def test_same_language_target_is_echoed_and_other_translated():
    emitted = []
    eng = live_engine(emitted, source=None, targets=("es", "en"))
    await eng.handle_message(msg(final="Hola a todos.", lang="es-419"))
    await eng.stop()
    done = emitted[-1]
    assert done.language == "es"
    assert done.translations == {"es": "Hola a todos.", "en": "[en] Hola a todos."}


def test_live_config_and_helpers():
    emitted = []
    eng = live_engine(emitted, GeminiLiveConfig(mode="VERBATIM"))
    cfg = eng.build_config()
    assert cfg.input_audio_transcription.language_codes == ["en-US"]
    assert cfg.input_audio_transcription.custom_vocabulary == ["Nerdearla"]
    assert cfg.input_audio_transcription.mode == types.AudioTranscriptionConfigMode.VERBATIM
    assert to_bcp47("es") == "es-419" and to_bcp47("pt-PT") == "pt-PT" and to_bcp47(None) is None
    assert parse_duration_s("9s") == 9.0 and parse_duration_s(None) == 5.0 and parse_duration_s("junk", 3) == 3


async def test_mock_engine_segments_jfk(jfk_pcm):
    emitted = []
    eng = MockEngine(make_ctx(emitted), MockTranslator(), delay_s=0)
    for i in range(0, len(jfk_pcm), 3200):
        await eng.feed(jfk_pcm[i : i + 3200])
    await eng.stop()
    finals = [c for c in emitted if c.status == CaptionStatus.final]
    translated = [c for c in emitted if c.status == CaptionStatus.translated]
    assert len(finals) >= 2 and len(translated) == len(finals)
    assert finals[0].t_start < finals[1].t_start
    assert all(c.translations["es"].startswith("[es] ") for c in translated)
