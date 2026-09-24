#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import typing
from pathlib import Path

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from transcriba.config import LATENCY_PROFILES, AppConfig

_spec = importlib.util.spec_from_file_location("config_reference_es", ROOT / "scripts" / "config_reference_es.py")
_es = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_es)

OUTPUTS = {"en": ROOT / "docs" / "CONFIGURATION.md", "es": ROOT / "docs" / "es" / "CONFIGURACION.md"}

HEADERS = {
    "en": """# Configuration reference

🇦🇷 [Versión en español](es/CONFIGURACION.md)

> Generated from `transcriba/config.py` by `python scripts/gen_config_reference.py`. Do not edit by hand.

The file is YAML. Unknown keys are errors (so a typo cannot slip through). `${VAR}` and `${VAR:-default}` are replaced with environment variables; the `.env` file next to the YAML is loaded automatically.

Keys under `engines` accept hyphens or underscores (`gemini-live` or `gemini_live`).

Minimal example:

```yaml
gemini: { api_key: ${GEMINI_API_KEY} }
server: { admin_token: ${TRANSCRIBA_ADMIN_TOKEN} }
defaults: { source_language: en, target_languages: [es] }
sessions:
  - { id: room-a, name: "Room A", source: browser }
```

""",
    "es": """# Referencia de configuración

🇬🇧 [English version](../CONFIGURATION.md)

> Generado automáticamente desde `transcriba/config.py` con `python scripts/gen_config_reference.py`. No editar a mano.

El archivo es YAML. Las claves desconocidas son un error (así un typo no pasa desapercibido). Los valores `${VAR}` y `${VAR:-default}` se reemplazan por variables de entorno; el archivo `.env` que esté junto al YAML se carga solo.

Las claves de `engines` aceptan guion o guion bajo (`gemini-live` o `gemini_live`).

Ejemplo mínimo:

```yaml
gemini: { api_key: ${GEMINI_API_KEY} }
server: { admin_token: ${TRANSCRIBA_ADMIN_TOKEN} }
defaults: { source_language: en, target_languages: [es] }
sessions:
  - { id: sala-a, name: "Sala A", source: browser }
```

""",
}

SECTION_NOTES = {
    "en": {
        "AppConfig": "Root of the configuration file.",
        "ServerConfig": "Web server: ports, authentication, persistence.",
        "GeminiConfig": "Gemini credentials (AI Studio API key or Vertex AI).",
        "EnginesConfig": "Settings of each engine. Only the one in use needs touching.",
        "GeminiLiveConfig": "`gemini-live` engine: streaming transcription + text translator. Inherits the Live session lifecycle (rotation, drain, idle).",
        "GeminiLiveTranslateConfig": "`gemini-live-translate` engine: a single model, speech → translated speech + transcripts.",
        "GeminiChunkedConfig": "`gemini-chunked` engine: WAV segments → generate_content (transcribes and translates in one call).",
        "VadConfig": "Energy-based voice activity detector used by the segment-based engines (gemini-chunked, local, mock).",
        "LocalConfig": "`local` engine: faster-whisper for transcription + Ollama (Gemma) for translation.",
        "TranslatorConfig": "Text translator used by gemini-live, gemini-chunked (extra targets) and local.",
        "SessionDefaults": "Defaults for every room; each room can override them.",
        "SessionConfig": "One room.",
    },
    "es": _es.SECTION_NOTES,
}

WORDS = {
    "en": {
        "str": "text",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "list": "list of",
        "dict": "map",
        "required": "**required**",
        "section": "(section)",
        "object": "(object)",
        "see": "(see description)",
        "empty": "empty",
        "cols": "| Key | Type | Default | Description |",
        "profiles": "## Latency profiles",
        "profiles_intro": "`latency_profile` sets these values unless they are written by hand in the YAML:",
        "profiles_cols": "| Profile | gemini-live | VAD (chunked/local) | translator |",
        "defaults": "default values",
    },
    "es": {
        "str": "texto",
        "int": "entero",
        "float": "número",
        "bool": "booleano",
        "list": "lista de",
        "dict": "mapa",
        "required": "**obligatorio**",
        "section": "(sección)",
        "object": "(objeto)",
        "see": "(ver descripción)",
        "empty": "vacío",
        "cols": "| Clave | Tipo | Default | Descripción |",
        "profiles": "## Perfiles de latencia",
        "profiles_intro": "`latency_profile` fija estos valores salvo que estén escritos a mano en el YAML:",
        "profiles_cols": "| Perfil | gemini-live | VAD (chunked/local) | translator |",
        "defaults": "valores por defecto",
    },
}


def type_name(annotation, w: dict) -> str:
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Union or str(origin) == "<class 'types.UnionType'>":
        return " \\| ".join(type_name(a, w) for a in args if a is not type(None)) + (" \\| null" if type(None) in args else "")
    if origin is typing.Literal:
        return " \\| ".join(f"`{a}`" for a in args)
    if origin in (list, typing.List):
        return f"{w['list']} {type_name(args[0], w)}" if args else w["list"].split()[0]
    if origin in (dict, typing.Dict):
        return w["dict"]
    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            return f"[{annotation.__name__}](#{annotation.__name__.lower()})"
        return w.get(annotation.__name__, annotation.__name__)
    return str(annotation)


def default_repr(field, w: dict) -> str:
    if field.default_factory is not None:
        try:
            val = field.default_factory()
        except TypeError:
            return w["object"]
        if isinstance(val, BaseModel):
            return w["section"]
        return f"`{val}`" if not isinstance(val, dict) else w["see"]
    if field.default is PydanticUndefined:
        return w["required"]
    if field.default == "":
        return '`""`'
    if field.default is None:
        return w["empty"]
    return f"`{field.default}`"


def description(model: type[BaseModel], name: str, field, lang: str) -> str:
    text = field.description or ""
    if lang == "es":
        text = _es.DESCRIPTIONS.get(f"{model.__name__}.{name}", text)
    return text.replace("|", "\\|")


def render_model(model: type[BaseModel], seen: set[type], out: list[str], lang: str) -> None:
    if model in seen:
        return
    seen.add(model)
    w = WORDS[lang]
    out.append(f"## {model.__name__}\n")
    note = SECTION_NOTES[lang].get(model.__name__)
    if note:
        out.append(note + "\n")
    out.append(w["cols"] + "\n|---|---|---|---|")
    nested: list[type[BaseModel]] = []
    for name, field in model.model_fields.items():
        key = field.alias or name
        out.append(f"| `{key}` | {type_name(field.annotation, w)} | {default_repr(field, w)} | {description(model, name, field, lang)} |")
        for candidate in [field.annotation, *typing.get_args(field.annotation)]:
            if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                nested.append(candidate)
    out.append("")
    for n in nested:
        render_model(n, seen, out, lang)


def build(lang: str) -> str:
    w = WORDS[lang]
    out: list[str] = [HEADERS[lang]]
    render_model(AppConfig, set(), out, lang)
    out.append(w["profiles"] + "\n")
    out.append(w["profiles_intro"] + "\n")
    out.append(w["profiles_cols"] + "\n|---|---|---|---|")
    for name, preset in LATENCY_PROFILES.items():
        fmt = lambda d: ", ".join(f"{k}={v}" for k, v in d.items()) or w["defaults"]
        out.append(
            f"| `{name}` | {fmt(preset.get('gemini_live', {}))} | {fmt(preset.get('vad', {}))} | {fmt(preset.get('translator', {}))} |"
        )
    out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    stale = []
    for lang, path in OUTPUTS.items():
        content = build(lang)
        if "--check" in sys.argv:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            print(f"written {path.relative_to(ROOT)} ({len(content.splitlines())} lines)")
    if stale:
        print("stale: " + ", ".join(stale) + " — run python scripts/gen_config_reference.py")
        sys.exit(1)
    if "--check" in sys.argv:
        print("configuration reference up to date (en, es)")
