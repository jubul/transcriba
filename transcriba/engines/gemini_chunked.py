from __future__ import annotations

import asyncio
import json
import logging
import random

from google import genai
from google.genai import errors, types

from transcriba.audio.pcm import pcm_to_wav
from transcriba.audio.segmenter import Segment
from transcriba.config import GeminiChunkedConfig
from transcriba.engines.base import EngineContext, SegmentingEngine, TranscribeResult
from transcriba.translators.base import Translator, language_name, parse_json_object, clean_translations
from transcriba.translators.gemini import thinking_config_for

log = logging.getLogger(__name__)

SYSTEM = """You are a live captioning engine for {domain}.
You receive a few seconds of audio from the stage. Do two things:
1. Transcribe the speech exactly as spoken, in the language spoken ({src}). Remove fillers (um, uh),
   keep technical terms, product names, code identifiers and proper nouns intact. Glossary (never translate,
   spell exactly like this): {glossary}
2. Translate the transcription into: {targets}. Concise, natural, faithful; subtitle register.
   If the speech is already in a target language, copy it unchanged for that key.
If there is no intelligible speech (noise, music, applause), return an empty "text".
The clip may start or end mid-sentence: transcribe the fragment as-is, do not invent words.
Return JSON only."""


class GeminiChunkedEngine(SegmentingEngine):
    name = "gemini-chunked"

    def __init__(self, ctx: EngineContext, translator: Translator | None, cfg: GeminiChunkedConfig, client: genai.Client) -> None:
        super().__init__(ctx, translator, cfg.vad, cfg.max_inflight)
        self.cfg = cfg
        self.client = client
        self._thinking = thinking_config_for(cfg.model, "off")
        self._thinking_ok = True
        self.info.update({"model": cfg.model, "requests": 0, "input_tokens": 0, "output_tokens": 0})

    def _schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "language": {"type": "string"},
                "translations": {
                    "type": "object",
                    "properties": {t: {"type": "string"} for t in self.ctx.target_languages},
                },
            },
            "required": ["text", "language", "translations"],
        }

    def _config(self) -> types.GenerateContentConfig:
        kw: dict = dict(
            system_instruction=SYSTEM.format(
                domain=self.ctx.domain,
                src=language_name(self.ctx.source_language) if self.ctx.source_language else "auto-detect",
                glossary=", ".join(self.ctx.glossary) or "(none)",
                targets=", ".join(f"{language_name(t)} (key '{t}')" for t in self.ctx.target_languages) or "(none)",
            ),
            temperature=0.1,
            max_output_tokens=1024,
            response_mime_type="application/json",
            response_json_schema=self._schema(),
            http_options=types.HttpOptions(timeout=int(self.cfg.timeout_s * 1000)),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        if self._thinking is not None and self._thinking_ok:
            kw["thinking_config"] = self._thinking
        return types.GenerateContentConfig(**kw)

    def _prompt(self) -> str:
        parts = []
        if self._history:
            parts.append("Previous utterances for context (do not repeat them):")
            parts += [f"- {o}" for o, _ in list(self._history)[-5:]]
        parts.append("Transcribe and translate the attached audio clip. JSON keys: text, language (ISO 639-1), translations.")
        return "\n".join(parts)

    async def transcribe(self, seg: Segment) -> TranscribeResult | None:
        wav = pcm_to_wav(seg.pcm)
        contents = [types.Part.from_bytes(data=wav, mime_type="audio/wav"), types.Part.from_text(text=self._prompt())]
        delay = 0.5
        for attempt in range(3):
            try:
                self.info["requests"] += 1
                resp = await self.client.aio.models.generate_content(model=self.cfg.model, contents=contents, config=self._config())
                usage = getattr(resp, "usage_metadata", None)
                if usage:
                    self.info["input_tokens"] += usage.prompt_token_count or 0
                    self.info["output_tokens"] += usage.candidates_token_count or 0
                obj = parse_json_object(resp.text or "{}")
                text = str(obj.get("text") or "").strip()
                lang = obj.get("language") or self.ctx.source_language
                tr = obj.get("translations") or {}
                return TranscribeResult(
                    text=text,
                    language=lang if isinstance(lang, str) else None,
                    translations=clean_translations(tr if isinstance(tr, dict) else {}, self.ctx.target_languages),
                )
            except errors.APIError as e:
                msg = str(e)
                if self._thinking_ok and "thinking" in msg.lower():
                    self._thinking_ok = False
                    continue
                code = getattr(e, "code", None)
                if code not in (408, 429, 500, 502, 503, 504) and not isinstance(e, errors.ServerError):
                    raise
                log.warning("[%s] chunked ASR attempt %d failed (%s)", self.ctx.session_id, attempt + 1, code)
            except (ValueError, json.JSONDecodeError) as e:
                log.warning("[%s] chunked ASR bad JSON: %s", self.ctx.session_id, e)
            await asyncio.sleep(delay + random.random() * 0.3)
            delay *= 2
        return None
