from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from transcriba.audio.pcm import pcm_to_float32
from transcriba.audio.segmenter import Segment
from transcriba.config import LocalConfig
from transcriba.engines.base import EngineContext, SegmentingEngine, TranscribeResult, base_lang
from transcriba.translators.base import Translator

log = logging.getLogger(__name__)

_models: dict[tuple[str, str, str], object] = {}
_models_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="whisper")

_HALLUCINATIONS = {
    "thank you.",
    "thanks for watching.",
    "thank you for watching.",
    "you",
    "bye.",
    "subtitles by the amara.org community",
    "gracias.",
    "gracias por ver.",
    "suscríbete.",
    "[música]",
    "[music]",
    "(music)",
    "♪",
}


_CUDA_ERR_MARKERS = ("libcublas", "libcudnn", "cuda", "cublas", "cudnn")


def _preload_cuda_libs() -> None:
    import ctypes
    import glob
    import os

    for mod in ("nvidia.cublas.lib", "nvidia.cudnn.lib"):
        try:
            m = __import__(mod, fromlist=["__file__"])
        except ImportError:
            continue
        for so in sorted(glob.glob(os.path.join(os.path.dirname(m.__file__), "*.so*"))):
            try:
                ctypes.CDLL(so, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass


def is_cuda_error(e: BaseException) -> bool:
    msg = str(e).lower()
    return any(k in msg for k in _CUDA_ERR_MARKERS)


def load_model(name: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    if device in ("auto", "cuda"):
        _preload_cuda_libs()
    key = (name, device, compute_type)
    with _models_lock:
        if key in _models:
            return _models[key]
        attempts = [(device, compute_type)]
        if device == "auto":
            attempts = [("cuda", compute_type if compute_type != "default" else "float16"), ("cpu", "int8")]
        last: Exception | None = None
        for dev, ct in attempts:
            try:
                log.info("loading faster-whisper %s on %s/%s", name, dev, ct)
                model = WhisperModel(name, device=dev, compute_type=ct)
                _models[key] = model
                return model
            except Exception as e:
                last = e
                log.warning("faster-whisper on %s failed: %s", dev, str(e)[:200])
        raise RuntimeError(f"could not load whisper model {name}: {last}")


class LocalWhisperEngine(SegmentingEngine):
    name = "local"

    def __init__(self, ctx: EngineContext, translator: Translator | None, cfg: LocalConfig) -> None:
        super().__init__(ctx, translator, cfg.vad, cfg.max_inflight)
        self.cfg = cfg
        self.model = None
        self.info.update({"whisper_model": cfg.whisper_model, "device": None})

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self.model = await loop.run_in_executor(_executor, load_model, self.cfg.whisper_model, self.cfg.device, self.cfg.compute_type)
        self.info["device"] = getattr(getattr(self.model, "model", None), "device", None) or "loaded"

    async def transcribe(self, seg: Segment) -> TranscribeResult | None:
        if self.model is None:
            await self.start()
        audio = pcm_to_float32(seg.pcm)
        lang = base_lang(self.ctx.source_language)
        prompt = ", ".join(self.ctx.glossary[:40]) or None

        def run() -> TranscribeResult | None:
            segments, info = self.model.transcribe(
                audio,
                language=lang,
                beam_size=self.cfg.beam_size,
                vad_filter=False,
                condition_on_previous_text=False,
                without_timestamps=True,
                initial_prompt=prompt,
            )
            texts = []
            for s in segments:
                if getattr(s, "no_speech_prob", 0.0) > 0.6 and getattr(s, "avg_logprob", 0.0) < -1.0:
                    continue
                t = s.text.strip()
                if t and t.lower() not in _HALLUCINATIONS:
                    texts.append(t)
            text = " ".join(texts).strip()
            if not text:
                return None
            detected = info.language if getattr(info, "language_probability", 1.0) >= 0.3 else lang
            return TranscribeResult(text=text, language=detected or lang)

        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(_executor, run)
        except Exception as e:
            if self.cfg.device == "cpu" or not is_cuda_error(e):
                raise
            log.warning(
                "[%s] CUDA inference failed (%s); falling back to CPU/int8. Install 'transcriba[cuda]' for GPU.",
                self.ctx.session_id,
                str(e)[:120],
            )
            self.model = await loop.run_in_executor(_executor, load_model, self.cfg.whisper_model, "cpu", "int8")
            self.cfg = self.cfg.model_copy(update={"device": "cpu", "compute_type": "int8"})
            self.info["device"] = "cpu (fallback)"
            return await loop.run_in_executor(_executor, run)
