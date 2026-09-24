# Contribuir

## Entorno

```bash
git clone … && cd transcriba
uv venv --python 3.12 && source .venv/bin/activate     # o python3 -m venv .venv
uv pip install -e ".[dev,local]"                        # o pip install -e ".[dev,local]"
pytest -q
```

Sin API key se puede desarrollar casi todo: el motor `mock`, el traductor `mock`, y los tests del Live API usan un servidor falso (`tests/test_live_session.py`). Para probar contra Gemini: `export GEMINI_API_KEY=…` o un `.env`, y `transcriba run samples/jfk.wav -e gemini-live --log-level debug`.

## Mapa del código

| Ruta | Qué hay |
|---|---|
| `transcriba/config.py` | Modelos pydantic de la configuración. Cada campo lleva `description`: de ahí sale `docs/CONFIGURACION.md`. |
| `transcriba/audio/` | `source.py` (ffmpeg y push desde navegador), `segmenter.py` (VAD por energía), `pcm.py` (helpers). |
| `transcriba/engines/` | `base.py` (interfaz `Engine`, `SegmentingEngine`, bookkeeping de subtítulos y traducción), `live_base.py` (ciclo de vida de sesiones Live), un archivo por motor. |
| `transcriba/translators/` | Interfaz + prompts compartidos (`base.py`), `gemini.py`, `ollama.py`, `mock.py`. |
| `transcriba/pipeline.py` | `SessionRunner` (una sala) y `SessionManager` (todas, con persistencia). |
| `transcriba/hub.py`, `store.py`, `export.py` | Pub/sub en memoria, JSONL, SRT/VTT/TXT. |
| `transcriba/server.py` | FastAPI: páginas, REST, WebSockets. |
| `transcriba/web/` | HTML/JS sin build: `audience`, `viewer`, `admin`, `ingest` + `static/pcm-worklet.js`. |
| `transcriba/cli.py` | `init`, `serve`, `run`, `check`, `export`, `devices`. |
| `tests/` | pytest + pytest-asyncio. `conftest.py` genera audio sintético y carga `samples/jfk.wav`. |
| `scripts/gen_config_reference.py` | Genera la referencia de configuración; CI falla si está desactualizada. |

## Agregar un motor

1. Crear `transcriba/engines/mi_motor.py`. Para ASR por segmentos, heredar de `SegmentingEngine` e implementar `async def transcribe(self, seg) -> TranscribeResult | None`; la base segmenta, traduce los destinos que falten y emite. Para streaming propio, heredar de `Engine` e implementar `start/feed/stop`, creando subtítulos con `self.new_caption(...)` y cerrándolos con `await self.finalize(cap, texto, idioma)`.
2. Registrarlo en `transcriba/engines/__init__.py` (`build_engine`) y en `ENGINE_NAMES` de `config.py`. Si necesita opciones, agregar un modelo en `EnginesConfig` con descripciones.
3. Test: ver `tests/test_engines.py` (eventos) y `tests/test_live_session.py` (ciclo de vida con servidor falso).
4. Regenerar la referencia: `python scripts/gen_config_reference.py`, y documentarlo en la tabla de motores del README.

## Convenciones

- El código no lleva comentarios ni docstrings: lo que haya que explicar va al README o a `docs/` (la arquitectura en `docs/ARQUITECTURA.md`, las opciones en las `description` de `config.py`, que generan `docs/CONFIGURACION.md`).
- Formato con `ruff format` (línea de 140); CI lo verifica.
- Identificadores en inglés; documentación y textos de interfaz en español (más `README.en.md`).
- Sin dependencias pesadas en el core: lo opcional va en extras (`local`, `cuda`).
- Los subtítulos tienen `id` estable y `seq`; los clientes hacen upsert. No romper ese contrato ([docs/API.md](docs/API.md)).
- Antes de un PR: `pytest -q`, `ruff format transcriba tests scripts` y `python scripts/gen_config_reference.py --check`.

## Publicar una versión

Subir `version` en `pyproject.toml` y `transcriba/__init__.py`, `pytest`, tag `vX.Y.Z`.
