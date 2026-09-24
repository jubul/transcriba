from __future__ import annotations

import asyncio
import logging

import httpx

from transcriba.config import TranslatorConfig
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


class OllamaTranslator(Translator):
    name = "ollama"

    def __init__(self, cfg: TranslatorConfig, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.cfg = cfg
        self.model = cfg.model if not cfg.model.startswith("gemini") else "gemma4:e4b"
        self.base_url = cfg.ollama_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=cfg.timeout_s, transport=transport)
        self._sem = asyncio.Semaphore(max(1, min(cfg.max_concurrency, 4)))
        self.stats = {"requests": 0, "errors": 0}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def translate(self, req: TranslationRequest) -> dict[str, str]:
        if not req.targets or not req.text.strip():
            return {}
        body = {
            "model": self.model,
            "stream": False,
            "format": json_schema_for(req.targets),
            "keep_alive": "60m",
            "options": {"temperature": self.cfg.temperature, "num_predict": 512},
            "messages": [
                {"role": "system", "content": build_system_prompt(req)},
                {"role": "user", "content": build_user_prompt(req)},
            ],
        }
        delay = 0.5
        for attempt in range(3):
            try:
                async with self._sem:
                    self.stats["requests"] += 1
                    r = await self._client.post("/api/chat", json=body)
                r.raise_for_status()
                content = r.json().get("message", {}).get("content", "")
                return clean_translations(parse_json_object(content), req.targets)
            except (httpx.HTTPError, ValueError) as e:
                self.stats["errors"] += 1
                log.warning("ollama translate attempt %d failed: %s", attempt + 1, str(e)[:200])
                await asyncio.sleep(delay)
                delay *= 2
        return {}

    async def healthy(self) -> tuple[bool, str]:
        try:
            r = await self._client.get("/api/tags")
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", [])]
            if not any(n == self.model or n.split(":")[0] == self.model.split(":")[0] for n in names):
                return False, f"model {self.model} not pulled (ollama pull {self.model}); available: {names}"
            return True, f"ollama ok, model {self.model}"
        except httpx.HTTPError as e:
            return False, f"ollama unreachable at {self.base_url}: {e}"
