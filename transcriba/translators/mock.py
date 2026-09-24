from __future__ import annotations

import asyncio

from transcriba.translators.base import TranslationRequest, Translator


class MockTranslator(Translator):
    name = "mock"

    def __init__(self, delay_s: float = 0.0) -> None:
        self.delay_s = delay_s
        self.calls: list[TranslationRequest] = []

    async def translate(self, req: TranslationRequest) -> dict[str, str]:
        self.calls.append(req)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        return {t: f"[{t}] {req.text}" for t in req.targets}


class NoopTranslator(Translator):
    name = "none"

    async def translate(self, req: TranslationRequest) -> dict[str, str]:
        return {}
