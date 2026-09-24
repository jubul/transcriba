from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from transcriba.audio.pcm import BYTES_PER_SECOND, rms_dbfs
from transcriba.audio.source import AudioSource, PushSource, make_source
from transcriba.config import AppConfig, SessionConfig
from transcriba.engines import EngineContext, build_engine
from transcriba.engines.base import Engine
from transcriba.hub import Hub
from transcriba.models import Caption, CaptionStatus, SessionState, SessionStatus
from transcriba.store import CaptionStore
from transcriba.translators import MockTranslator, build_translator
from transcriba.translators.base import Translator

log = logging.getLogger(__name__)


class SessionRunner:
    def __init__(self, cfg: SessionConfig, app: AppConfig, hub: Hub, store: CaptionStore) -> None:
        self.cfg = cfg
        self.app = app
        self.hub = hub
        self.store = store
        self.state = SessionState.stopped
        self.error: str | None = None
        self.source: AudioSource | None = None
        self.engine: Engine | None = None
        self.translator: Translator | None = None
        self._task: asyncio.Task | None = None
        self.stream_bytes = 0
        self.level_dbfs = -100.0
        self.captions = 0
        self.last_caption: Caption | None = None
        self.started_at: float | None = None
        self.audio_seconds_total = 0.0

    @property
    def id(self) -> str:
        return self.cfg.id

    @property
    def engine_name(self) -> str:
        return self.app.engine_for(self.cfg)

    @property
    def source_language(self) -> str | None:
        return self.app.source_language_for(self.cfg)

    @property
    def target_languages(self) -> list[str]:
        return self.app.target_languages_for(self.cfg)

    def clock(self) -> float:
        return self.stream_bytes / BYTES_PER_SECOND

    async def start(self) -> None:
        if self.state in (SessionState.running, SessionState.starting):
            return
        self.state, self.error = SessionState.starting, None
        await self.publish_status()
        try:
            tr_cfg = self.app.translator_for(self.cfg)
            try:
                self.translator = build_translator(tr_cfg, self.app.gemini)
            except RuntimeError as e:
                if self.engine_name == "mock":
                    log.warning("[%s] %s; using mock translator", self.id, e)
                    self.translator = MockTranslator()
                else:
                    raise
            ctx = EngineContext(
                session_id=self.id,
                source_language=self.source_language,
                target_languages=self.target_languages,
                glossary=self.app.glossary_for(self.cfg),
                language_notes=self.app.defaults.language_notes,
                emit=self._on_caption,
                clock=self.clock,
                audio_out=self._on_audio,
                context_size=tr_cfg.context_size,
            )
            self.engine = build_engine(self.engine_name, ctx, self.app, self.translator)
            self.source = make_source(self.cfg.source, self.cfg.source_args, loop=self.cfg.loop)
            await self.engine.start()
            await self.source.start()
            self.started_at = time.time()
            self.store.write_meta(
                self.id,
                {
                    "id": self.id,
                    "name": self.cfg.name,
                    "engine": self.engine_name,
                    "source": self.cfg.source,
                    "source_language": self.source_language,
                    "target_languages": self.target_languages,
                    "started_at": self.started_at,
                },
            )
            self.state = SessionState.running
            self._task = asyncio.create_task(self._pump(), name=f"session:{self.id}")
        except Exception as e:
            self.state, self.error = SessionState.error, f"{type(e).__name__}: {e}"
            log.exception("[%s] failed to start", self.id)
            await self._teardown()
            await self.publish_status()
            raise

    async def _pump(self) -> None:
        assert self.source is not None and self.engine is not None
        await self.publish_status()
        last_status = time.monotonic()
        try:
            async for chunk in self.source:
                self.stream_bytes += len(chunk)
                self.audio_seconds_total += len(chunk) / BYTES_PER_SECOND
                self.level_dbfs = rms_dbfs(chunk)
                await self.engine.feed(chunk)
                now = time.monotonic()
                if now - last_status >= 1.0:
                    last_status = now
                    await self.publish_status()
            log.info("[%s] source ended; flushing", self.id)
            await self.engine.stop()
            self.state = SessionState.stopped
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.state, self.error = SessionState.error, f"{type(e).__name__}: {e}"
            log.exception("[%s] pipeline crashed", self.id)
        finally:
            await self.publish_status()

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        await self._teardown()
        if self.state != SessionState.error:
            self.state = SessionState.stopped
        await self.publish_status()

    async def _teardown(self) -> None:
        src, self.source = self.source, None
        eng, self.engine = self.engine, None
        tr, self.translator = self.translator, None
        if src is not None:
            try:
                await src.stop()
            except Exception:
                log.exception("[%s] source stop failed", self.id)
        if eng is not None:
            try:
                await eng.stop()
            except Exception:
                log.exception("[%s] engine stop failed", self.id)
        if tr is not None:
            try:
                await tr.aclose()
            except Exception:
                pass
        self.store.close(self.id)

    @property
    def accepts_push(self) -> bool:
        return isinstance(self.source, PushSource)

    def push_audio(self, pcm: bytes) -> bool:
        if isinstance(self.source, PushSource):
            self.source.push(pcm)
            return True
        return False

    def set_ingest_connected(self, connected: bool) -> None:
        if isinstance(self.source, PushSource):
            self.source.connected = connected

    async def _on_caption(self, cap: Caption) -> None:
        if cap.status != CaptionStatus.partial:
            self.last_caption = cap
            if cap.status == CaptionStatus.final:
                self.captions += 1
        await self.hub.publish(cap)
        if cap.status == CaptionStatus.translated:
            await self.store.append(cap)

    async def _on_audio(self, pcm: bytes, sample_rate: int) -> None:
        await self.hub.publish_audio(self.id, pcm)

    def status(self) -> SessionStatus:
        last = self.last_caption
        tr_text = ""
        if last is not None:
            for lang in self.target_languages:
                if lang in last.translations and lang != last.language:
                    tr_text = last.translations[lang]
                    break
        return SessionStatus(
            id=self.id,
            name=self.cfg.name or self.id,
            state=self.state,
            engine=self.engine_name,
            source=self.cfg.source,
            source_language=self.source_language,
            target_languages=self.target_languages,
            stream_time=self.clock(),
            level_dbfs=self.level_dbfs,
            captions=self.captions,
            last_caption_ts=last.ts if last else None,
            last_original=last.original if last else "",
            last_translation=tr_text,
            error=self.error,
            ingest_connected=isinstance(self.source, PushSource) and self.source.connected,
            viewers=self.hub.viewers(self.id),
            audio_minutes=round(self.audio_seconds_total / 60.0, 2),
            engine_info=dict(self.engine.info) if self.engine is not None else {},
        )

    async def publish_status(self) -> None:
        await self.hub.publish_status(self.id, self.status().model_dump(mode="json"))


class SessionManager:
    def __init__(self, app: AppConfig, hub: Hub, store: CaptionStore) -> None:
        self.app = app
        self.hub = hub
        self.store = store
        self.runners: dict[str, SessionRunner] = {}
        self.persist_path = self.store.root / "sessions.json"
        self._runtime_ids: set[str] = set()

    def add(self, cfg: SessionConfig, persist: bool = False) -> SessionRunner:
        if cfg.id in self.runners:
            raise KeyError(f"session {cfg.id} already exists")
        runner = SessionRunner(cfg, self.app, self.hub, self.store)
        self.runners[cfg.id] = runner
        if persist:
            self._runtime_ids.add(cfg.id)
            self._save()
        return runner

    def get(self, session_id: str) -> SessionRunner | None:
        return self.runners.get(session_id)

    async def remove(self, session_id: str) -> None:
        runner = self.runners.pop(session_id, None)
        if runner is not None:
            await runner.stop()
            self.hub.clear(session_id)
            await self.hub.publish_removed(session_id)
        if session_id in self._runtime_ids:
            self._runtime_ids.discard(session_id)
            self._save()

    def _save(self) -> None:
        payload = [
            self.runners[i].cfg.model_dump(mode="json", exclude_defaults=True) for i in sorted(self._runtime_ids) if i in self.runners
        ]
        try:
            self.persist_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            log.warning("could not persist sessions to %s: %s", self.persist_path, e)

    def _load_persisted(self) -> list[SessionConfig]:
        if not self.persist_path.exists():
            return []
        try:
            raw = json.loads(self.persist_path.read_text(encoding="utf-8"))
            return [SessionConfig.model_validate(item) for item in raw]
        except (OSError, ValueError) as e:
            log.warning("ignoring unreadable %s: %s", self.persist_path, e)
            return []

    async def start_all(self) -> None:
        for cfg in self.app.sessions:
            if cfg.id not in self.runners:
                self.add(cfg)
        for cfg in self._load_persisted():
            if cfg.id not in self.runners:
                self._runtime_ids.add(cfg.id)
                self.add(cfg)
                log.info("[%s] restored session created from the panel", cfg.id)
        to_start = [r for r in self.runners.values() if r.cfg.autostart]
        results = await asyncio.gather(*(r.start() for r in to_start), return_exceptions=True)
        for r, res in zip(to_start, results):
            if isinstance(res, Exception):
                log.error("[%s] autostart failed: %s", r.id, res)

    async def stop_all(self) -> None:
        await asyncio.gather(*(r.stop() for r in self.runners.values()), return_exceptions=True)

    def statuses(self) -> list[dict[str, Any]]:
        return [r.status().model_dump(mode="json") for r in self.runners.values()]
