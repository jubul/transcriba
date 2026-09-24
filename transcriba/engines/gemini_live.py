from __future__ import annotations

import asyncio
import logging

from google import genai
from google.genai import types

from transcriba.config import GeminiLiveConfig
from transcriba.engines.base import EngineContext, base_lang
from transcriba.engines.live_base import LiveSessionEngine
from transcriba.models import Caption, CaptionStatus
from transcriba.translators.base import Translator

log = logging.getLogger(__name__)

SENTENCE_END = (".", "?", "!", "…", '."', '?"', '!"', ".»", "?»", "!»", ".)", "?)", "!)")

BCP47_DEFAULTS = {
    "en": "en-US",
    "es": "es-419",
    "pt": "pt-BR",
    "fr": "fr-FR",
    "de": "de-DE",
    "it": "it-IT",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "zh": "cmn-Hans-CN",
    "ru": "ru-RU",
    "nl": "nl-NL",
    "pl": "pl-PL",
    "tr": "tr-TR",
    "ar": "ar-XA",
    "hi": "hi-IN",
    "ca": "ca-ES",
    "eu": "eu-ES",
    "gl": "gl-ES",
}


def to_bcp47(code: str | None) -> str | None:
    if not code:
        return None
    if "-" in code:
        return code
    return BCP47_DEFAULTS.get(code.lower(), code)


_SENS = {
    "start": {"high": types.StartSensitivity.START_SENSITIVITY_HIGH, "low": types.StartSensitivity.START_SENSITIVITY_LOW},
    "end": {"high": types.EndSensitivity.END_SENSITIVITY_HIGH, "low": types.EndSensitivity.END_SENSITIVITY_LOW},
}


class GeminiLiveEngine(LiveSessionEngine):
    name = "gemini-live"

    def __init__(self, ctx: EngineContext, translator: Translator | None, cfg: GeminiLiveConfig, client: genai.Client) -> None:
        super().__init__(ctx, translator, cfg, client, cfg.asr_model)
        self.cfg = cfg
        self._cur: Caption | None = None
        self._final_buf = ""
        self._flush_handle: asyncio.TimerHandle | None = None
        self.info.update({"partials": 0})

    def build_config(self) -> types.LiveConnectConfig:
        src = to_bcp47(self.ctx.source_language)
        tc = types.AudioTranscriptionConfig(
            language_codes=[src] if src else [],
            custom_vocabulary=self.ctx.glossary[:1000] or None,
            mode=types.AudioTranscriptionConfigMode.SMART if self.cfg.mode == "SMART" else types.AudioTranscriptionConfigMode.VERBATIM,
        )
        kw: dict = dict(response_modalities=[types.Modality.TEXT], input_audio_transcription=tc)
        aad: dict = {}
        if self.cfg.start_sensitivity != "default":
            aad["start_of_speech_sensitivity"] = _SENS["start"][self.cfg.start_sensitivity]
        if self.cfg.end_sensitivity != "default":
            aad["end_of_speech_sensitivity"] = _SENS["end"][self.cfg.end_sensitivity]
        if self.cfg.silence_duration_ms is not None:
            aad["silence_duration_ms"] = self.cfg.silence_duration_ms
        if self.cfg.prefix_padding_ms is not None:
            aad["prefix_padding_ms"] = self.cfg.prefix_padding_ms
        if aad:
            kw["realtime_input_config"] = types.RealtimeInputConfig(automatic_activity_detection=types.AutomaticActivityDetection(**aad))
        return types.LiveConnectConfig(**kw)

    async def handle_message(self, msg: types.LiveServerMessage) -> None:
        sc = msg.server_content
        if sc is None:
            if log.isEnabledFor(logging.DEBUG) and msg.setup_complete is None:
                log.debug("[%s] live msg: %s", self.ctx.session_id, msg.model_dump_json(exclude_none=True)[:400])
            return
        interim = sc.interim_input_transcription
        final = sc.input_transcription
        if log.isEnabledFor(logging.DEBUG) and (interim is not None or final is not None or sc.turn_complete):
            log.debug(
                "[%s] live event interim=%r | final=%r finished=%r lang=%r | turn_complete=%r",
                self.ctx.session_id,
                interim.text if interim else None,
                final.text if final else None,
                final.finished if final else None,
                (final or interim).language_code if (final or interim) else None,
                sc.turn_complete,
            )
        if interim is not None and interim.text and self.cfg.emit_partials:
            await self._on_interim(interim.text, interim.language_code)
        if final is not None and final.text:
            await self._on_final_chunk(final.text, final.finished, final.language_code)

    def _ensure_current(self) -> Caption:
        if self._cur is None:
            self._cur = self.new_caption(CaptionStatus.partial, t_start=self.ctx.clock())
        return self._cur

    async def _on_interim(self, text: str, lang: str | None) -> None:
        cap = self._ensure_current()
        text = text.strip()
        if self._final_buf and not text.lower().startswith(self._final_buf.lower()[: max(8, len(self._final_buf) - 4)]):
            shown = f"{self._final_buf} {text}"
        else:
            shown = text
        if shown == cap.original:
            return
        cap.original = shown
        if lang:
            cap.language = base_lang(lang)
        self.info["partials"] += 1
        await self.emit(cap)

    async def _on_final_chunk(self, text: str, finished: bool | None, lang: str | None) -> None:
        cap = self._ensure_current()
        self._final_buf = f"{self._final_buf} {text.strip()}".strip()
        if lang:
            cap.language = base_lang(lang)
        ends_sentence = self._final_buf.endswith(SENTENCE_END)
        if finished is True or (finished is None and ends_sentence):
            await self._commit()
            return
        cap.original = self._final_buf
        await self.emit(cap)
        self._arm_flush(self.cfg.final_chunk_timeout_s if ends_sentence else self.cfg.final_chunk_max_wait_s)

    def _arm_flush(self, delay: float) -> None:
        self._cancel_flush()
        loop = asyncio.get_running_loop()
        self._flush_handle = loop.call_later(delay, lambda: self.spawn(self._commit()))

    def _cancel_flush(self) -> None:
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None

    async def _commit(self) -> None:
        self._cancel_flush()
        cap, text = self._cur, self._final_buf
        self._cur, self._final_buf = None, ""
        if cap is None:
            return
        if not text.strip():
            return
        await self.finalize(cap, text, cap.language, t_end=self.ctx.clock())

    async def on_session_end(self) -> None:
        if self._cur is not None and not self._final_buf and self._cur.original:
            self._final_buf = self._cur.original
        await self._commit()
