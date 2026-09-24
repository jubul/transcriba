from __future__ import annotations

import asyncio
import logging
import random

from google import genai
from google.genai import errors, types

from transcriba.config import GeminiConfig, TranslatorConfig
from transcriba.translators.base import (
    TranslationRequest,
    Translator,
    build_system_prompt,
    build_user_prompt,
    clean_translations,
    json_schema_for,
    parse_json_object,
)

log = logging.getLogger(__name__)

_RETRYABLE = {408, 429, 500, 502, 503, 504}


def make_client(gemini_cfg: GeminiConfig | None) -> genai.Client:
    gemini_cfg = gemini_cfg or GeminiConfig()
    if gemini_cfg.vertexai:
        return genai.Client(vertexai=True, project=gemini_cfg.project or None, location=gemini_cfg.location or None)
    key = gemini_cfg.resolve_api_key()
    if not key:
        raise RuntimeError("Gemini API key missing: set GEMINI_API_KEY (https://aistudio.google.com/apikey) or gemini.api_key in config")
    return genai.Client(api_key=key)


def thinking_config_for(model: str, mode: str) -> types.ThinkingConfig | None:
    if mode != "off":
        return None
    if "2.5" in model or "2.0" in model:
        return types.ThinkingConfig(thinking_budget=0)
    return types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)


class GeminiTranslator(Translator):
    name = "gemini"
    _semaphores: dict[int, asyncio.Semaphore] = {}

    def __init__(self, cfg: TranslatorConfig, gemini_cfg: GeminiConfig | None = None, client: genai.Client | None = None) -> None:
        self.cfg = cfg
        self.client = client or make_client(gemini_cfg)
        self.model = cfg.model
        self._thinking = thinking_config_for(self.model, cfg.thinking)
        self._thinking_ok = True
        self.stats = {"requests": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0}

    def _sem(self) -> asyncio.Semaphore:
        key = id(asyncio.get_running_loop())
        sem = self._semaphores.get(key)
        if sem is None:
            sem = self._semaphores[key] = asyncio.Semaphore(self.cfg.max_concurrency)
        return sem

    def _config(self, req: TranslationRequest) -> types.GenerateContentConfig:
        kw: dict = dict(
            system_instruction=build_system_prompt(req),
            temperature=self.cfg.temperature,
            max_output_tokens=1024,
            response_mime_type="application/json",
            response_json_schema=json_schema_for(req.targets),
            http_options=types.HttpOptions(timeout=int(self.cfg.timeout_s * 1000)),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        if self._thinking is not None and self._thinking_ok:
            kw["thinking_config"] = self._thinking
        return types.GenerateContentConfig(**kw)

    async def translate(self, req: TranslationRequest) -> dict[str, str]:
        if not req.targets or not req.text.strip():
            return {}
        prompt = build_user_prompt(req)
        delay = 0.5
        last_exc: Exception | None = None
        for attempt in range(4):
            try:
                async with self._sem():
                    self.stats["requests"] += 1
                    resp = await self.client.aio.models.generate_content(model=self.model, contents=prompt, config=self._config(req))
                usage = getattr(resp, "usage_metadata", None)
                if usage:
                    self.stats["input_tokens"] += usage.prompt_token_count or 0
                    self.stats["output_tokens"] += usage.candidates_token_count or 0
                text = resp.text or ""
                return clean_translations(parse_json_object(text), req.targets)
            except errors.APIError as e:
                last_exc = e
                self.stats["errors"] += 1
                code = getattr(e, "code", None) or getattr(e, "status", None)
                msg = str(e)
                if self._thinking_ok and "thinking" in msg.lower():
                    log.warning("model %s rejected thinking_config; disabling (%s)", self.model, msg[:120])
                    self._thinking_ok = False
                    continue
                if code not in _RETRYABLE and not isinstance(e, errors.ServerError):
                    log.error("gemini translate failed (non-retryable %s): %s", code, msg[:300])
                    break
                log.warning("gemini translate attempt %d failed (%s); retrying in %.1fs", attempt + 1, code, delay)
            except (ValueError, asyncio.TimeoutError, OSError) as e:
                last_exc = e
                self.stats["errors"] += 1
                log.warning("gemini translate attempt %d error: %s", attempt + 1, str(e)[:200])
            await asyncio.sleep(delay + random.random() * 0.3)
            delay = min(delay * 2, 6.0)
        log.error("gemini translate gave up: %s", last_exc)
        return {}
