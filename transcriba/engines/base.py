from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from transcriba.audio.segmenter import Segment, Segmenter
from transcriba.config import VadConfig
from transcriba.models import Caption, CaptionStatus
from transcriba.translators.base import TranslationRequest, Translator, same_language
from transcriba.translators.mock import NoopTranslator

log = logging.getLogger(__name__)

AudioOut = Callable[[bytes, int], Awaitable[None]]


@dataclass
class EngineContext:
    session_id: str
    source_language: str | None
    target_languages: list[str]
    glossary: list[str]
    language_notes: dict[str, str]
    emit: Callable[[Caption], Awaitable[None]]
    clock: Callable[[], float]
    audio_out: AudioOut | None = None
    context_size: int = 6
    domain: str = "a technology conference talk"


@dataclass
class TranscribeResult:
    text: str
    language: str | None = None
    translations: dict[str, str] = field(default_factory=dict)


def base_lang(code: str | None) -> str | None:
    return code.split("-")[0].lower() if code else None


class Engine(ABC):
    name = "engine"

    def __init__(self, ctx: EngineContext, translator: Translator | None = None) -> None:
        self.ctx = ctx
        self.translator: Translator = translator or NoopTranslator()
        self._seq = 0
        self._history: deque[tuple[str, dict[str, str]]] = deque(maxlen=max(1, ctx.context_size))
        self._tasks: set[asyncio.Task] = set()
        self.info: dict[str, Any] = {"captions": 0, "translation_errors": 0}

    async def start(self) -> None:
        return None

    @abstractmethod
    async def feed(self, pcm: bytes) -> None: ...

    async def stop(self) -> None:
        pending = [t for t in self._tasks if not t.done()]
        if pending:
            await asyncio.wait(pending, timeout=5)
        for t in self._tasks:
            if not t.done():
                t.cancel()
        self._tasks.clear()

    def new_caption(
        self,
        status: CaptionStatus = CaptionStatus.partial,
        original: str = "",
        language: str | None = None,
        t_start: float | None = None,
        t_end: float | None = None,
    ) -> Caption:
        self._seq += 1
        return Caption(
            id=f"{self.ctx.session_id}-{self._seq:06d}",
            session_id=self.ctx.session_id,
            seq=self._seq,
            status=status,
            original=original,
            language=base_lang(language) or (self.ctx.source_language if status != CaptionStatus.partial else None),
            t_start=self.ctx.clock() if t_start is None else t_start,
            t_end=t_end,
            engine=self.name,
        )

    async def emit(self, cap: Caption) -> None:
        cap.touch()
        try:
            await self.ctx.emit(cap)
        except Exception:
            log.exception("emit failed for %s", cap.id)

    async def finalize(
        self,
        cap: Caption,
        original: str,
        language: str | None = None,
        t_end: float | None = None,
        translations: dict[str, str] | None = None,
    ) -> None:
        cap.original = original.strip()
        cap.language = base_lang(language) or cap.language or self.ctx.source_language
        cap.t_end = self.ctx.clock() if t_end is None else t_end
        if translations:
            cap.translations.update(translations)
        cap.status = CaptionStatus.final
        self.info["captions"] += 1
        await self.emit(cap)
        self.spawn(self._translate_and_emit(cap))

    def spawn(self, coro: Awaitable[Any]) -> asyncio.Task:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def missing_targets(self, cap: Caption) -> list[str]:
        src = cap.language or self.ctx.source_language
        return [t for t in self.ctx.target_languages if t not in cap.translations and not same_language(t, src)]

    async def _translate_and_emit(self, cap: Caption) -> None:
        src = cap.language or self.ctx.source_language
        for t in self.ctx.target_languages:
            if same_language(t, src) and t not in cap.translations:
                cap.translations[t] = cap.original
        targets = self.missing_targets(cap)
        if targets and cap.original:
            req = TranslationRequest(
                text=cap.original,
                source_language=src,
                targets=targets,
                context=list(self._history),
                glossary=self.ctx.glossary,
                language_notes=self.ctx.language_notes,
                domain=self.ctx.domain,
            )
            try:
                result = await self.translator.translate(req)
            except Exception as e:
                log.exception("translator crashed")
                result = {}
                cap.meta["translation_error"] = str(e)[:200]
            cap.translations.update(result)
            missing = [t for t in targets if t not in result]
            if missing:
                self.info["translation_errors"] += 1
                cap.meta["translation_error"] = f"missing translations: {', '.join(missing)}"
        cap.status = CaptionStatus.translated
        await self.emit(cap)
        if cap.original:
            self._history.append((cap.original, dict(cap.translations)))


class SegmentingEngine(Engine):
    def __init__(
        self,
        ctx: EngineContext,
        translator: Translator | None = None,
        vad: VadConfig | None = None,
        max_inflight: int = 2,
    ) -> None:
        super().__init__(ctx, translator)
        self.segmenter = Segmenter(vad or VadConfig())
        self._sem = asyncio.Semaphore(max(1, max_inflight))
        self.info.update({"segments": 0, "asr_errors": 0, "inflight": 0})

    async def feed(self, pcm: bytes) -> None:
        for seg in self.segmenter.feed(pcm):
            self._dispatch(seg)

    async def stop(self) -> None:
        seg = self.segmenter.flush()
        if seg is not None:
            self._dispatch(seg)
        await super().stop()

    def _dispatch(self, seg: Segment) -> None:
        self.info["segments"] += 1
        cap = self.new_caption(CaptionStatus.partial, t_start=seg.start_s, t_end=seg.end_s)
        self.spawn(self._run_segment(cap, seg))

    async def _run_segment(self, cap: Caption, seg: Segment) -> None:
        async with self._sem:
            self.info["inflight"] += 1
            try:
                res = await self.transcribe(seg)
            except Exception as e:
                self.info["asr_errors"] += 1
                self.info["last_error"] = f"{type(e).__name__}: {e}"[:300]
                log.warning("[%s] ASR failed for segment @%.1fs: %s", self.ctx.session_id, seg.start_s, e)
                return
            finally:
                self.info["inflight"] -= 1
        if not res or not res.text.strip():
            return
        await self.finalize(cap, res.text, res.language, t_end=seg.end_s, translations=res.translations)

    @abstractmethod
    async def transcribe(self, seg: Segment) -> TranscribeResult | None: ...
