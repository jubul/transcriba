from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict, defaultdict
from typing import Any

from transcriba.models import Caption

log = logging.getLogger(__name__)

ALL = "*"


class Hub:
    def __init__(self, history_size: int = 200, queue_size: int = 500) -> None:
        self.history_size = history_size
        self.queue_size = queue_size
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._audio_subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._history: dict[str, OrderedDict[str, Caption]] = defaultdict(OrderedDict)
        self.last_status: dict[str, dict[str, Any]] = {}

    def subscribe(self, session_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self.queue_size)
        self._subs[session_id].add(q)
        return q

    def unsubscribe(self, session_id: str, q: asyncio.Queue) -> None:
        self._subs[session_id].discard(q)

    def subscribe_audio(self, session_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self.queue_size)
        self._audio_subs[session_id].add(q)
        return q

    def unsubscribe_audio(self, session_id: str, q: asyncio.Queue) -> None:
        self._audio_subs[session_id].discard(q)

    def viewers(self, session_id: str) -> int:
        return len(self._subs.get(session_id, ()))

    def history(self, session_id: str) -> list[Caption]:
        caps = list(self._history.get(session_id, {}).values())
        caps.sort(key=lambda c: c.seq)
        return caps

    def clear(self, session_id: str) -> None:
        self._history.pop(session_id, None)

    @staticmethod
    def _offer(q: asyncio.Queue, item: Any) -> None:
        try:
            q.put_nowait(item)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            q.put_nowait(item)

    def _broadcast(self, session_id: str, payload: str) -> None:
        for q in list(self._subs.get(session_id, ())):
            self._offer(q, payload)

    async def publish(self, cap: Caption) -> None:
        hist = self._history[cap.session_id]
        hist[cap.id] = cap
        hist.move_to_end(cap.id)
        while len(hist) > self.history_size:
            hist.popitem(last=False)
        self._broadcast(cap.session_id, json.dumps({"type": "caption", "data": cap.model_dump(mode="json")}, ensure_ascii=False))

    async def publish_status(self, session_id: str, status: dict[str, Any]) -> None:
        self.last_status[session_id] = status
        payload = json.dumps({"type": "status", "data": status}, ensure_ascii=False)
        self._broadcast(session_id, payload)
        self._broadcast(ALL, payload)

    async def publish_removed(self, session_id: str) -> None:
        self.last_status.pop(session_id, None)
        self._broadcast(ALL, json.dumps({"type": "removed", "data": {"id": session_id}}))

    async def publish_audio(self, session_id: str, pcm: bytes) -> None:
        for q in list(self._audio_subs.get(session_id, ())):
            self._offer(q, pcm)

    def snapshot_message(self, session_id: str) -> str:
        return json.dumps(
            {
                "type": "history",
                "data": [c.model_dump(mode="json") for c in self.history(session_id)],
                "status": self.last_status.get(session_id),
            },
            ensure_ascii=False,
        )
