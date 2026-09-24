from transcriba.translators.base import Translator, TranslationRequest
from transcriba.translators.mock import MockTranslator, NoopTranslator


def build_translator(cfg, gemini_cfg=None) -> Translator:
    if cfg.provider == "gemini":
        from transcriba.translators.gemini import GeminiTranslator

        return GeminiTranslator(cfg, gemini_cfg)
    if cfg.provider == "ollama":
        from transcriba.translators.ollama import OllamaTranslator

        return OllamaTranslator(cfg)
    if cfg.provider == "mock":
        return MockTranslator()
    return NoopTranslator()


__all__ = ["Translator", "TranslationRequest", "MockTranslator", "NoopTranslator", "build_translator"]
