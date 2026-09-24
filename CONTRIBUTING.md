# Contributing

## Environment

```bash
git clone https://github.com/jubul/transcriba && cd transcriba
uv venv --python 3.12 && source .venv/bin/activate     # or python3 -m venv .venv
uv pip install -e ".[dev,local]" ruff                    # or pip install -e ".[dev,local]" ruff
pytest -q
```

Almost everything can be developed without an API key: the `mock` engine, the `mock` translator, and the Live API tests use a fake server (`tests/test_live_session.py`). To test against Gemini: `export GEMINI_API_KEY=…` or a `.env`, then `transcriba run samples/jfk.wav -e gemini-live --log-level debug`.

## Code map

| Path | Contents |
|---|---|
| `transcriba/config.py` | Pydantic configuration models. Every field carries a `description`: `docs/CONFIGURATION.md` and `docs/es/CONFIGURACION.md` are generated from them. |
| `transcriba/audio/` | `source.py` (ffmpeg and browser push), `segmenter.py` (energy VAD), `pcm.py` (helpers). |
| `transcriba/engines/` | `base.py` (the `Engine` interface, `SegmentingEngine`, caption and translation bookkeeping), `live_base.py` (Live session lifecycle), one file per engine. |
| `transcriba/translators/` | Interface + shared prompts (`base.py`), `gemini.py`, `ollama.py`, `mock.py`. |
| `transcriba/pipeline.py` | `SessionRunner` (one room) and `SessionManager` (all rooms, with persistence). |
| `transcriba/hub.py`, `store.py`, `export.py` | In-memory pub/sub, JSONL, SRT/VTT/TXT. |
| `transcriba/server.py` | FastAPI: pages, REST, WebSockets. |
| `transcriba/web/` | HTML/JS without a build step: `audience`, `viewer`, `admin`, `ingest` + `static/pcm-worklet.js`. |
| `transcriba/cli.py` | `init`, `serve`, `run`, `check`, `export`, `devices`. |
| `tests/` | pytest + pytest-asyncio. `conftest.py` generates synthetic audio and loads `samples/jfk.wav`. |
| `scripts/gen_config_reference.py` | Generates the configuration reference in both languages; CI fails if it is stale. Spanish descriptions live in `scripts/config_reference_es.py`. |

## Adding an engine

1. Create `transcriba/engines/my_engine.py`. For segment-based ASR, subclass `SegmentingEngine` and implement `async def transcribe(self, seg) -> TranscribeResult | None`; the base class segments, translates the missing targets and emits. For your own streaming, subclass `Engine` and implement `start/feed/stop`, creating captions with `self.new_caption(...)` and closing them with `await self.finalize(cap, text, language)`.
2. Register it in `transcriba/engines/__init__.py` (`build_engine`) and in `ENGINE_NAMES` in `config.py`. If it needs options, add a model to `EnginesConfig` with descriptions (and their Spanish counterparts in `scripts/config_reference_es.py`).
3. Tests: see `tests/test_engines.py` (events) and `tests/test_live_session.py` (lifecycle with a fake server).
4. Regenerate the reference: `python scripts/gen_config_reference.py`, and document it in the engines table of the README.

## Conventions

- The code carries no comments or docstrings: anything that needs explaining goes to the README or `docs/` (architecture in `docs/ARCHITECTURE.md`, options in the `description` fields of `config.py`, which generate `docs/CONFIGURATION.md`).
- Formatting with `ruff format` (line length 140); CI checks it.
- Code, identifiers, documentation and configuration in English. Spanish translations of the docs live in `README.es.md` and `docs/es/`. The web UI and CLI messages are in Spanish for now (see the roadmap).
- Captions have a stable `id` and a `seq`; clients upsert. Do not break that contract ([docs/API.md](docs/API.md)).
- No heavy dependencies in the core: optional things go into extras (`local`, `cuda`).
- Before a PR: `pytest -q`, `ruff format transcriba tests scripts` and `python scripts/gen_config_reference.py --check`.

## Releasing

Bump `version` in `pyproject.toml` and `transcriba/__init__.py`, update `CHANGELOG.md`, `pytest`, tag `vX.Y.Z`, `gh release create vX.Y.Z --generate-notes`.
