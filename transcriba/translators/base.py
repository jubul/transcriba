from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

LANGUAGE_NAMES = {
    "es": "Spanish",
    "en": "English",
    "pt": "Portuguese",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "ja": "Japanese",
    "zh": "Chinese",
    "ko": "Korean",
    "ru": "Russian",
    "ar": "Arabic",
    "hi": "Hindi",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "ca": "Catalan",
    "eu": "Basque",
    "gl": "Galician",
    "qu": "Quechua",
    "gn": "Guarani",
}


def language_name(code: str | None) -> str:
    if not code:
        return "the source language"
    base = code.split("-")[0].lower()
    return LANGUAGE_NAMES.get(base, code)


def same_language(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a.split("-")[0].lower() == b.split("-")[0].lower()


@dataclass
class TranslationRequest:
    text: str
    source_language: str | None
    targets: list[str]
    context: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    glossary: list[str] = field(default_factory=list)
    language_notes: dict[str, str] = field(default_factory=dict)
    domain: str = "a technology conference talk"


class Translator(ABC):
    name: str = "translator"

    @abstractmethod
    async def translate(self, req: TranslationRequest) -> dict[str, str]: ...

    async def aclose(self) -> None:
        return None


SYSTEM_PROMPT = """You are a professional simultaneous interpreter producing live subtitles for {domain}.
You receive one short utterance (a few seconds of speech) at a time, plus the preceding utterances for context.
Translate ONLY the current utterance. Rules:
- Faithful and complete, but concise: subtitles are read quickly. Never add commentary.
- Keep the speaker's tone and register. Keep sentence boundaries; do not merge with context.
- Keep technical terms, product names, code identifiers, acronyms and proper nouns as-is
  when that is how practitioners say them in the target language (e.g. Kubernetes, pull request, deploy, API).
- Never translate glossary terms: {glossary}
- If the utterance is a fragment (cut mid-sentence), translate the fragment naturally; do not complete it.
- If the utterance is already in the target language, return it unchanged (fix obvious ASR typos only).
- Output strictly JSON with one key per target language code and string values.
{notes}"""


def build_system_prompt(req: TranslationRequest) -> str:
    notes = "\n".join(f"- Style for {language_name(t)} ({t}): {req.language_notes[t]}" for t in req.targets if t in req.language_notes)
    glossary = ", ".join(req.glossary) if req.glossary else "(none)"
    return SYSTEM_PROMPT.format(domain=req.domain, glossary=glossary, notes=notes)


def build_user_prompt(req: TranslationRequest) -> str:
    src = language_name(req.source_language)
    targets = ", ".join(f"{language_name(t)} ({t})" for t in req.targets)
    parts = [f"Source language: {src}. Target languages: {targets}."]
    if req.context:
        parts.append("Previous utterances (context only, do NOT translate):")
        for original, tr in req.context[-8:]:
            line = f"  - {original}"
            if tr:
                line += "  =>  " + " | ".join(f"[{k}] {v}" for k, v in tr.items())
            parts.append(line)
    parts.append("Current utterance to translate:")
    parts.append(req.text)
    parts.append("Respond with JSON only, e.g. " + json.dumps({t: "..." for t in req.targets}, ensure_ascii=False))
    return "\n".join(parts)


def json_schema_for(targets: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {t: {"type": "string"} for t in targets},
        "required": list(targets),
    }


_JSON_RE = re.compile(r"\{.*\}", re.S)


def parse_json_object(text: str) -> dict:
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    m = _JSON_RE.search(text)
    if not m:
        raise ValueError(f"no JSON object in model output: {text[:200]!r}")
    obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("model output JSON is not an object")
    return obj


def clean_translations(obj: dict, targets: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for t in targets:
        v = obj.get(t)
        if v is None:
            for k, vv in obj.items():
                if isinstance(k, str) and (k.lower().startswith(t.lower()) or language_name(t).lower() == k.lower()):
                    v = vv
                    break
        if isinstance(v, str) and v.strip():
            out[t] = v.strip()
    return out
