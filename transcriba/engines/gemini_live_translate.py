from __future__ import annotations

import logging
from collections import deque

from google import genai
from google.genai import types

from transcriba.config import GeminiLiveTranslateConfig
from transcriba.engines.base import EngineContext, base_lang
from transcriba.engines.live_base import LiveSessionEngine
from transcriba.models import Caption, CaptionStatus
from transcriba.translators.base import Translator

log = logging.getLogger(__name__)

OUTPUT_SAMPLE_RATE = 24_000


class GeminiLiveTranslateEngine(LiveSessionEngine):
    name = "gemini-live-translate"

    def __init__(self, ctx: EngineContext, translator: Translator | None, cfg: GeminiLiveTranslateConfig, client: genai.Client) -> None:
        super().__init__(ctx, translator, cfg, client, cfg.model)
        self.cfg = cfg
        if not ctx.target_languages:
            raise ValueError("gemini-live-translate needs at least one target language")
        self.target = ctx.target_languages[0]
        self._cur: Caption | None = None
        self._in_buf = ""
        self._out_buf = ""
        self._pending: deque[Caption] = deque()
        self.info.update({"target": self.target, "audio_bytes": 0})

    def build_config(self) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            translation_config=types.TranslationConfig(
                target_language_code=self.target,
                echo_target_language=self.cfg.echo_target_language,
            ),
        )

    async def handle_message(self, msg: types.LiveServerMessage) -> None:
        sc = msg.server_content
        if sc is None:
            return
        if sc.input_transcription is not None and sc.input_transcription.text:
            await self._on_input(sc.input_transcription)
        if sc.output_transcription is not None and sc.output_transcription.text:
            await self._on_output(sc.output_transcription)
        if self.cfg.stream_audio and self.ctx.audio_out is not None and sc.model_turn is not None:
            for part in sc.model_turn.parts or []:
                data = getattr(getattr(part, "inline_data", None), "data", None)
                if data:
                    self.info["audio_bytes"] += len(data)
                    await self.ctx.audio_out(data, OUTPUT_SAMPLE_RATE)

    async def _on_input(self, tr: types.Transcription) -> None:
        if self._cur is None:
            self._cur = self.new_caption(CaptionStatus.partial, t_start=self.ctx.clock())
        self._in_buf = f"{self._in_buf} {tr.text.strip()}".strip()
        if tr.language_code:
            self._cur.language = base_lang(tr.language_code)
        self._cur.original = self._in_buf
        if tr.finished is False:
            await self.emit(self._cur)
            return
        cap, self._cur, self._in_buf = self._cur, None, ""
        cap.status = CaptionStatus.final
        cap.t_end = self.ctx.clock()
        self.info["captions"] += 1
        await self.emit(cap)
        self._pending.append(cap)
        if len(self._pending) > 6:
            stale = self._pending.popleft()
            self.spawn(self._translate_and_emit(stale))

    async def _on_output(self, tr: types.Transcription) -> None:
        self._out_buf = f"{self._out_buf} {tr.text.strip()}".strip()
        if tr.finished is False:
            return
        text, self._out_buf = self._out_buf, ""
        if not text:
            return
        if self._pending:
            cap = self._pending.popleft()
        else:
            cap = self.new_caption(CaptionStatus.final, original="", t_start=self.ctx.clock())
            cap.t_end = cap.t_start
        cap.translations[self.target] = text
        self.spawn(self._translate_and_emit(cap))

    async def on_session_end(self) -> None:
        if self._cur is not None and self._in_buf:
            cap, self._cur, self._in_buf = self._cur, None, ""
            cap.status = CaptionStatus.final
            cap.t_end = self.ctx.clock()
            await self.emit(cap)
            self._pending.append(cap)
        if self._out_buf and self._pending:
            cap = self._pending.popleft()
            cap.translations[self.target] = self._out_buf
            self._out_buf = ""
            self.spawn(self._translate_and_emit(cap))
        while self._pending:
            self.spawn(self._translate_and_emit(self._pending.popleft()))
