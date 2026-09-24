from __future__ import annotations

import json
from typing import Iterable

from transcriba.models import Caption, CaptionStatus


def _ts(seconds: float, sep: str) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        s, ms = s + 1, 0
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def caption_text(cap: Caption, lang: str) -> str:
    if lang == "orig":
        return cap.original
    if lang == "both":
        tr = "\n".join(v for k, v in cap.translations.items() if k != cap.language and v)
        return "\n".join(x for x in (cap.original, tr) if x)
    return cap.translations.get(lang) or ("" if cap.translations else cap.original)


def timed(caps: Iterable[Caption]) -> list[tuple[float, float, Caption]]:
    items = [c for c in caps if c.status != CaptionStatus.partial and (c.original or c.translations)]
    items.sort(key=lambda c: c.seq)
    out: list[tuple[float, float, Caption]] = []
    for i, c in enumerate(items):
        start = c.t_start
        end = c.t_end if c.t_end is not None and c.t_end > start else start + max(1.5, len(c.original) / 15.0)
        if i + 1 < len(items):
            end = min(end, max(start + 0.5, items[i + 1].t_start))
        out.append((start, end, c))
    return out


def to_srt(caps: Iterable[Caption], lang: str = "both") -> str:
    lines = []
    for n, (start, end, c) in enumerate(timed(caps), 1):
        text = caption_text(c, lang)
        if not text:
            continue
        lines += [str(n), f"{_ts(start, ',')} --> {_ts(end, ',')}", text, ""]
    return "\n".join(lines)


def to_vtt(caps: Iterable[Caption], lang: str = "both") -> str:
    lines = ["WEBVTT", ""]
    for start, end, c in timed(caps):
        text = caption_text(c, lang)
        if not text:
            continue
        lines += [f"{_ts(start, '.')} --> {_ts(end, '.')}", text, ""]
    return "\n".join(lines)


def to_txt(caps: Iterable[Caption], lang: str = "orig") -> str:
    parts = []
    for start, _end, c in timed(caps):
        text = caption_text(c, lang)
        if text:
            parts.append(f"[{_ts(start, '.')[:8]}] {text}" if lang != "both" else f"[{_ts(start, '.')[:8]}]\n{text}\n")
    return "\n".join(parts) + ("\n" if parts else "")


def to_jsonl(caps: Iterable[Caption]) -> str:
    return "".join(json.dumps(c.model_dump(mode="json"), ensure_ascii=False) + "\n" for c in caps)


FORMATS = {
    "srt": (to_srt, "application/x-subrip"),
    "vtt": (to_vtt, "text/vtt"),
    "txt": (to_txt, "text/plain"),
    "jsonl": (None, "application/x-ndjson"),
}


def render(caps: list[Caption], fmt: str, lang: str) -> tuple[str, str]:
    if fmt == "jsonl":
        return to_jsonl(caps), FORMATS[fmt][1]
    fn, mime = FORMATS[fmt]
    return fn(caps, lang), mime
