from __future__ import annotations

import asyncio

from transcriba.audio.segmenter import Segment
from transcriba.config import VadConfig
from transcriba.engines.base import EngineContext, SegmentingEngine, TranscribeResult
from transcriba.translators.base import Translator

DEMO_LINES = [
    "Welcome everyone, thanks for joining this session.",
    "Today we are going to talk about observability at scale.",
    "The first thing you need is good instrumentation in your services.",
    "We moved from a monolith to about forty microservices in two years.",
    "Kubernetes made deployments easier, but debugging got harder.",
    "So we adopted OpenTelemetry for traces, metrics and logs.",
    "The key insight is that context propagation is everything.",
    "Let me show you a quick demo of the pipeline.",
    "Any questions so far? Feel free to interrupt me.",
    "Great, let's move on to the alerting strategy.",
]


class MockEngine(SegmentingEngine):
    name = "mock"

    def __init__(
        self,
        ctx: EngineContext,
        translator: Translator | None = None,
        vad: VadConfig | None = None,
        *,
        delay_s: float = 0.05,
        lines: list[str] | None = None,
    ) -> None:
        super().__init__(ctx, translator, vad, max_inflight=4)
        self.delay_s = delay_s
        self.lines = lines or DEMO_LINES
        self._n = 0

    async def transcribe(self, seg: Segment) -> TranscribeResult:
        await asyncio.sleep(self.delay_s)
        text = self.lines[self._n % len(self.lines)]
        self._n += 1
        return TranscribeResult(text=f"{text} ({seg.duration_s:.1f}s)", language=self.ctx.source_language or "en")
