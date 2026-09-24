from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, TextIO

from transcriba.models import Caption

log = logging.getLogger(__name__)


class CaptionStore:
    def __init__(self, data_dir: str | Path) -> None:
        self.root = Path(data_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self._files: dict[str, TextIO] = {}

    def session_dir(self, session_id: str) -> Path:
        d = self.root / session_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _file(self, session_id: str) -> TextIO:
        f = self._files.get(session_id)
        if f is None or f.closed:
            f = self._files[session_id] = (self.session_dir(session_id) / "captions.jsonl").open("a", encoding="utf-8")
        return f

    async def append(self, cap: Caption) -> None:
        f = self._file(cap.session_id)
        f.write(json.dumps(cap.model_dump(mode="json"), ensure_ascii=False) + "\n")
        f.flush()

    def write_meta(self, session_id: str, meta: dict[str, Any]) -> None:
        meta = {**meta, "updated_at": time.time()}
        (self.session_dir(session_id) / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, session_id: str) -> list[Caption]:
        path = self.root / session_id / "captions.jsonl"
        if not path.exists():
            return []
        by_id: dict[str, Caption] = {}
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    cap = Caption.model_validate_json(line)
                except ValueError:
                    log.warning("skipping bad line in %s", path)
                    continue
                by_id[cap.id] = cap
        return sorted(by_id.values(), key=lambda c: c.seq)

    def list_sessions(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if (p / "captions.jsonl").exists())

    def close(self, session_id: str | None = None) -> None:
        ids = [session_id] if session_id else list(self._files)
        for sid in ids:
            f = self._files.pop(sid, None)
            if f:
                f.close()
