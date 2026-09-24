from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CaptionStatus(str, Enum):
    partial = "partial"
    final = "final"
    translated = "translated"


class Caption(BaseModel):
    id: str
    session_id: str
    seq: int
    status: CaptionStatus
    original: str = ""
    language: str | None = None
    translations: dict[str, str] = Field(default_factory=dict)
    t_start: float = 0.0
    t_end: float | None = None
    ts: float = Field(default_factory=time.time)
    engine: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    def touch(self) -> "Caption":
        self.ts = time.time()
        return self


class SessionState(str, Enum):
    stopped = "stopped"
    starting = "starting"
    running = "running"
    error = "error"


class SessionStatus(BaseModel):
    id: str
    name: str
    state: SessionState
    engine: str
    source: str
    source_language: str | None
    target_languages: list[str]
    stream_time: float = 0.0
    level_dbfs: float = -100.0
    captions: int = 0
    last_caption_ts: float | None = None
    last_original: str = ""
    last_translation: str = ""
    error: str | None = None
    ingest_connected: bool = False
    viewers: int = 0
    audio_minutes: float = 0.0
    engine_info: dict[str, Any] = Field(default_factory=dict)
