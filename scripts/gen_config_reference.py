#!/usr/bin/env python3
from __future__ import annotations

import sys
import typing
from pathlib import Path

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transcriba.config import AppConfig, LATENCY_PROFILES

OUT = Path(__file__).resolve().parents[1] / "docs" / "CONFIGURACION.md"

HEADER = """# Referencia de configuración

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

"""


def type_name(annotation) -> str:
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Union or str(origin) == "<class 'types.UnionType'>":
        return " \\| ".join(type_name(a) for a in args if a is not type(None)) + (" \\| null" if type(None) in args else "")
    if origin is typing.Literal:
        return " \\| ".join(f"`{a}`" for a in args)
    if origin in (list, typing.List):
        return f"lista de {type_name(args[0])}" if args else "lista"
    if origin in (dict, typing.Dict):
        return "mapa"
    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            return f"[{annotation.__name__}](#{annotation.__name__.lower()})"
        return {"str": "texto", "int": "entero", "float": "número", "bool": "booleano"}.get(annotation.__name__, annotation.__name__)
    return str(annotation)


def default_repr(field) -> str:
    if field.default_factory is not None:
        try:
            val = field.default_factory()
        except TypeError:
            return "(objeto)"
        if isinstance(val, BaseModel):
            return "(sección)"
        return f"`{val}`" if not isinstance(val, dict) else "(ver descripción)"
    if field.default is PydanticUndefined:
        return "**obligatorio**"
    return f"`{field.default}`" if field.default not in ("", None) else ('`""`' if field.default == "" else "vacío")


SECTION_NOTES = {
    "AppConfig": "Raíz del archivo de configuración.",
    "ServerConfig": "Servidor web: puertos, autenticación, persistencia.",
    "GeminiConfig": "Credenciales de Gemini (API key de AI Studio o Vertex AI).",
    "EnginesConfig": "Ajustes de cada motor. Solo hace falta tocar el que se usa.",
    "GeminiLiveConfig": "Motor `gemini-live`: transcripción en streaming + traductor de texto. Hereda el ciclo de vida de sesiones Live (rotación, drenaje, inactividad).",
    "GeminiLiveTranslateConfig": "Motor `gemini-live-translate`: un solo modelo, voz → voz traducida + transcripciones.",
    "GeminiChunkedConfig": "Motor `gemini-chunked`: segmentos WAV → generate_content (transcribe y traduce en una llamada).",
    "VadConfig": "Detector de actividad de voz por energía, usado por los motores por segmentos (gemini-chunked, local, mock).",
    "LocalConfig": "Motor `local`: faster-whisper para transcribir + Ollama (Gemma) para traducir.",
    "TranslatorConfig": "Traductor de texto usado por gemini-live, gemini-chunked (destinos extra) y local.",
    "SessionDefaults": "Valores por defecto para todas las salas; cada sala puede pisarlos.",
    "SessionConfig": "Una sala.",
}


def render_model(model: type[BaseModel], seen: set[type], out: list[str]) -> None:
    if model in seen:
        return
    seen.add(model)
    out.append(f"## {model.__name__}\n")
    if model.__name__ in SECTION_NOTES:
        out.append(SECTION_NOTES[model.__name__] + "\n")
    out.append("| Clave | Tipo | Default | Descripción |\n|---|---|---|---|")
    nested: list[type[BaseModel]] = []
    for name, field in model.model_fields.items():
        key = field.alias or name
        out.append(f"| `{key}` | {type_name(field.annotation)} | {default_repr(field)} | {(field.description or '').replace('|', '\\|')} |")
        for candidate in [field.annotation, *typing.get_args(field.annotation)]:
            if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                nested.append(candidate)
    out.append("")
    for n in nested:
        render_model(n, seen, out)


def build() -> str:
    out: list[str] = [HEADER]
    render_model(AppConfig, set(), out)
    out.append("## Perfiles de latencia\n")
    out.append("`latency_profile` fija estos valores salvo que estén escritos a mano en el YAML:\n")
    out.append("| Perfil | gemini-live | VAD (chunked/local) | translator |\n|---|---|---|---|")
    for name, preset in LATENCY_PROFILES.items():
        fmt = lambda d: ", ".join(f"{k}={v}" for k, v in d.items()) or "valores por defecto"
        out.append(
            f"| `{name}` | {fmt(preset.get('gemini_live', {}))} | {fmt(preset.get('vad', {}))} | {fmt(preset.get('translator', {}))} |"
        )
    out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    content = build()
    if "--check" in sys.argv:
        if OUT.read_text(encoding="utf-8") != content:
            print(f"{OUT} está desactualizado: correr python scripts/gen_config_reference.py")
            sys.exit(1)
        print("docs/CONFIGURACION.md al día")
    else:
        OUT.write_text(content, encoding="utf-8")
        print(f"escrito {OUT} ({len(content.splitlines())} líneas)")
