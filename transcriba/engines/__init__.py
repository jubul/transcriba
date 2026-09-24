from __future__ import annotations

from transcriba.config import AppConfig
from transcriba.engines.base import Engine, EngineContext, SegmentingEngine, TranscribeResult
from transcriba.translators.base import Translator

_client_cache: dict[str, object] = {}


def gemini_client(app_cfg: AppConfig):
    from transcriba.translators.gemini import make_client

    key = repr(app_cfg.gemini.model_dump())
    if key not in _client_cache:
        _client_cache[key] = make_client(app_cfg.gemini)
    return _client_cache[key]


def build_engine(name: str, ctx: EngineContext, app_cfg: AppConfig, translator: Translator | None) -> Engine:
    if name == "mock":
        from transcriba.engines.mock import MockEngine

        return MockEngine(ctx, translator, app_cfg.engines.gemini_chunked.vad)
    if name == "gemini-live":
        from transcriba.engines.gemini_live import GeminiLiveEngine

        return GeminiLiveEngine(ctx, translator, app_cfg.engines.gemini_live, gemini_client(app_cfg))
    if name == "gemini-live-translate":
        from transcriba.engines.gemini_live_translate import GeminiLiveTranslateEngine

        return GeminiLiveTranslateEngine(ctx, translator, app_cfg.engines.gemini_live_translate, gemini_client(app_cfg))
    if name == "gemini-chunked":
        from transcriba.engines.gemini_chunked import GeminiChunkedEngine

        return GeminiChunkedEngine(ctx, translator, app_cfg.engines.gemini_chunked, gemini_client(app_cfg))
    if name == "local":
        from transcriba.engines.local_whisper import LocalWhisperEngine

        return LocalWhisperEngine(ctx, translator, app_cfg.engines.local)
    raise ValueError(f"unknown engine: {name}")


__all__ = ["Engine", "EngineContext", "SegmentingEngine", "TranscribeResult", "build_engine", "gemini_client"]
