# transcriba

[![CI](https://github.com/jubul/transcriba/actions/workflows/ci.yml/badge.svg)](https://github.com/jubul/transcriba/actions/workflows/ci.yml) [![License Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE) [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab.svg)](pyproject.toml) [![Code of conduct](https://img.shields.io/badge/code%20of%20conduct-Contributor%20Covenant%202.1-5e0d73.svg)](CODE_OF_CONDUCT.md)

🇦🇷 [Leer en español](README.es.md)

**Live captions for conferences, at scale, open source.** transcriba takes the audio of every stage and produces real-time subtitles in the original language and translated (English → Spanish, Spanish → English, or any pair you need), for 5, 10 or 30 rooms in parallel. Attendees pick a room and a language on their phones; the room shows the captions on screen or as an overlay on the stream.

Built on **Gemini**'s audio capabilities (Live API), with a **fully local** path using **Whisper + Gemma** through Ollama. Apache-2.0.

```
stage audio ─► transcriba ─► "…and that's why context propagation matters."   (< 1 s)
                             "…y por eso importa la propagación de contexto."  (~2-3 s)
```

| Document | What for |
|---|---|
| This README | What it is, 5-minute install, concepts |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Runbook to deploy and run it at a conference (server, per-room capture, event day, exports) |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Reference of every YAML option (generated from the code) |
| [docs/LATENCY.md](docs/LATENCY.md) | What determines speed and how to tune it |
| [docs/COSTS.md](docs/COSTS.md) | Model prices, cost per room-hour and per event |
| [docs/API.md](docs/API.md) | REST and WebSockets to integrate other viewers or systems |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it is built and why |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup, tests, how to add an engine |
| [CHANGELOG.md](CHANGELOG.md) · [SECURITY.md](SECURITY.md) · [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Releases, vulnerability reports, community rules |

Spanish versions of every document live in [docs/es/](docs/es/).

## What it solves

| Need | How |
|---|---|
| Live audio → real-time subtitles | Streaming to Gemini's Live API (`gemini-3.5-transcribe-live`): interim hypotheses in under a second, final sentences at each pause, translation of every sentence with context and glossary in about a second. |
| Original language + Spanish (and Spanish → English) | Any language pair per room. With `source_language: auto` and `target_languages: [es, en]`, each sentence is translated into the other language, whichever one was spoken. |
| Many sessions in parallel | One process handles dozens of rooms. Each room has its own audio source, engine, languages and glossary; rooms are created, started and stopped from the panel without touching the others. |
| OSI license and deployment guide | Apache-2.0 and a runbook written for volunteers at any conference. |
| Audience view | The home page lists the live rooms; each person picks a language and reads on their phone. The same viewer serves the room screen and works as a transparent OBS overlay. QR code per room. |

## Get started in 5 minutes

Requirements: Python 3.10 or newer and `ffmpeg` on the PATH (`apt install ffmpeg`, `brew install ffmpeg`, or the Windows installer).

```bash
git clone https://github.com/jubul/transcriba && cd transcriba
python3 -m venv .venv && source .venv/bin/activate        # with uv: uv venv --python 3.12 && source .venv/bin/activate
pip install -e .                                            # with uv: uv pip install -e .

transcriba init        # wizard: event name, API key, languages, number of rooms → transcriba.yaml + .env
transcriba check       # verifies ffmpeg, credentials, models
transcriba serve       # starts everything and prints the URLs
```

`transcriba init` asks for a Gemini API key (create one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey); Google Developers credits apply there), generates an admin token and creates one room per stage. The resulting `.env` is loaded automatically on every start: no exporting variables.

On startup, `serve` prints the three URLs that matter:

- **Audience**: `http://<ip>:8000/` to pick a room and a language.
- **Panel**: `http://<ip>:8000/admin` to operate (asks for the token from `.env`).
- **Ingest**: `http://<ip>:8000/ingest/<room>` to send audio from the laptop in each room.

No credentials and no real audio? There is a complete demo: `transcriba serve -c config/demo.yaml` (token `demo`).

Docker: `cp .env.example .env`, edit it, `docker compose up -d`. Optional profiles: `--profile rtmp` adds an RTMP server to receive OBS; `--profile local` adds Ollama.

## Try it with your microphone

```bash
transcriba serve -c config/mic.yaml
```
Open `http://localhost:8000/ingest/mic?token=mic`, press "Empezar a enviar" (start) and allow the microphone. In another tab, `http://localhost:8000/view/mic?lang=both`. Speak Spanish or English: what you said appears first, and the translation one or two seconds later. On WSL2 it also works straight from the terminal with the Windows microphone: `transcriba run pulse:default -e gemini-live -l es -t en`.

## How the audio gets in

The `source` field of each room accepts:

| `source` | Typical case |
|---|---|
| `browser` | A laptop next to the mixing desk opens `/ingest/<room>` and streams from the browser (microphone, USB interface or system audio). Reconnects by itself if the wifi drops. |
| `rtmp://…`, `srt://…`, `https://…/x.m3u8` | Take the audio from the stream: OBS or vMix push to an nginx-rtmp (bundled in the compose file). |
| `pulse:default`, `alsa:hw:1,0`, `avfoundation::0`, `dshow:audio=…` | Capture device on the machine running transcriba (`transcriba devices` lists them). |
| `talk.mp4`, `audio.mp3` | Files, played in real time (`loop: true` for demos). |
| `ffmpeg:<args>` | Anything ffmpeg can read. |

Everything is normalized to 16 kHz mono PCM; ffmpeg does the dirty work.

## Engines and cost

Chosen per room with `engine:`.

| Engine | What it uses | Latency | Cost per room-hour | When |
|---|---|---|---|---|
| `gemini-live` (recommended) | `gemini-3.5-transcribe-live` (streaming ASR, custom vocabulary) + `gemini-3.5-flash-lite` (translation with context) | original < 1 s, translation +1-2 s | ≈ US$ 0.70 | Production. N target languages. |
| `gemini-live-translate` | `gemini-3.5-live-translate-preview`: a single model, speech → translated speech + transcripts | 2-4 s | ≈ US$ 2.20 | You also want translated audio for headphones (🔊 button in the viewer). Experimental. |
| `gemini-chunked` | Local VAD → WAV clips → `gemini-3.5-flash-lite` transcribes and translates in one call | 3-8 s | ≈ US$ 0.20 | Cheap, works on the free tier, no WebSockets. |
| `local` | `faster-whisper` (ASR) + Gemma 4 on Ollama (translation) | 3-8 s | US$ 0 + GPU | No cloud. A desktop GPU handles 3-5 rooms. |
| `mock` | Real VAD, fake text | — | 0 | Demos, tests, operations rehearsal. |

A 30-talk conference (30 × 45 min ≈ 22.5 room-hours) costs **≈ US$ 16 with `gemini-live`**, within the US$ 25 credit. Live sessions are only open while audio flows, so a room waiting for its ingest costs nothing. Details in [docs/COSTS.md](docs/COSTS.md).

## Latency

Speed depends little on the model and a lot on **when a sentence is considered finished**: the model waits for a pause, transcriba waits for the chunk to close a sentence, and only then translates. The original text shows while the speaker talks; the translation follows one or two seconds after the pause. One setting controls it:

```yaml
latency_profile: fast      # shorter, quicker sentences
latency_profile: balanced  # default
latency_profile: quality   # complete sentences, better translation
```

Also `transcriba run … --latency fast` to compare from the terminal. What each profile changes and how to fine-tune by hand: [docs/LATENCY.md](docs/LATENCY.md).

## Configuration

One YAML file, generated by `transcriba init` and editable by hand ([full example](config/transcriba.example.yaml), [reference of every key](docs/CONFIGURATION.md)):

```yaml
latency_profile: balanced
server: { title: "Nerdearla 2026", admin_token: ${TRANSCRIBA_ADMIN_TOKEN}, public_url: https://subs.nerdearla.com }
gemini: { api_key: ${GEMINI_API_KEY} }
defaults:
  engine: gemini-live
  source_language: en
  target_languages: [es]
  glossary: [Nerdearla, sysarmy, Kubernetes, OpenTelemetry]
sessions:
  - { id: room-a, name: "Room A · Keynotes", source: rtmp://localhost/live/room-a }
  - { id: room-b, name: "Room B · Workshops", source: browser, source_language: auto, target_languages: [es, en] }
  - { id: room-c, name: "Room C", source: pulse:default, engine: local, source_language: es, target_languages: [en],
      translator: { provider: ollama, model: "gemma4:e4b" } }
```

Unknown keys are errors, so a typo cannot slip through. Rooms created from the panel are saved to `data/sessions.json` and come back after a restart.

## Views

- **`/`** audience: live rooms with one button per language. Works on any phone.
- **`/view/<room>?lang=es`** viewer. Parameters: `lang=orig|es|both|…`, `size=1.4`, `lines=2`, `theme=light`, `history=1` (full transcript with timestamps), `overlay=1` (transparent background for the OBS "Browser" source). The gear ⚙︎ changes everything live, copies the link and shows the QR code.
- **`/admin`** operations: state, audio level, captions emitted, people watching, latest texts, engine details and errors; create, start, stop and delete rooms; links to viewer, overlay, ingest, QR and SRT/TXT exports.
- **`/ingest/<room>`** browser ingest: pick the device, watch the level, and the page explains any problem (token, permissions, stopped room).

The web UI and CLI messages are currently in Spanish (the project was born at a Latin American conference); the code, docs and configuration are in English.

## Running many rooms

Each room is an independent session inside the same process. Rooms are defined in the YAML or created on the fly from the panel (or with `POST /api/sessions`). Stopping or restarting one does not affect the others, and transcripts are appended to each room's JSONL without ever being erased. For event day, the runbook is in [docs/OPERATIONS.md](docs/OPERATIONS.md): what to wire, what to watch in the panel, what to do when something fails and how to export at the end.

One process is enough for dozens of rooms with cloud engines. For more, or for redundancy, run several processes (one per track or building) behind a reverse proxy.

## Fully local

```bash
pip install -e ".[local]"          # faster-whisper; ".[cuda]" adds the NVIDIA libraries for GPU
ollama pull gemma4:e4b              # or gemma4:12b if you have the VRAM
```
In the room: `engine: local` with `translator: { provider: ollama, model: gemma4:e4b }`. Whisper runs on the GPU when CUDA is available and falls back to the CPU when libraries are missing. Gemma 4 E2B/E4B understand audio natively; a pure Gemma-audio engine is the natural next step.

## API

REST and WebSockets are documented in [docs/API.md](docs/API.md). Every caption has a stable `id`, a `seq`, a `status` (`partial` → `final` → `translated`), `original`, `language`, `translations`, `t_start`/`t_end`. Clients upsert by `id`, so building another viewer (an app, an LED wall) takes a few dozen lines.

## Development

```bash
pip install -e ".[dev,local]"
pytest -q                                      # 37 tests
python scripts/gen_config_reference.py         # regenerates docs/CONFIGURATION.md and docs/es/CONFIGURACION.md from the models
transcriba run samples/jfk.wav -e mock --no-realtime
```
Guide in [CONTRIBUTING.md](CONTRIBUTING.md).

## Status and limitations

- Tested with real microphone audio against the Live API (`gemini-live`): interim results, finals and translation work. Session rotation at 9 minutes is tested against a fake Live API; it still has to be observed during a full talk.
- Live models cap each session at ~10 minutes: transcriba rotates during a pause of the speaker; in the worst case a short sentence can be lost at the rotation.
- `gemini-live-translate` pairs original and translation by arrival order (experimental).
- The energy-based VAD is simple on purpose; in very noisy rooms tune `vad.speech_threshold_db` or use `gemini-live` (it uses the model's VAD).
- No database: state lives in the process and in `data/<room>/captions.jsonl` + `data/sessions.json`.

## Roadmap

- Pure Gemma-audio engine (Gemma 4 E4B) through Transformers or Ollama: local transcription and translation in one model.
- Retroactive caption correction with long context.
- Automatic publication of transcripts when each talk ends (Markdown/HTML).
- Prometheus metrics per room (latency, tokens, errors).
- English (and other) translations of the web UI and CLI.

## Community

- Used it, or planning to, at your conference? Tell us in [Discussions](https://github.com/jubul/transcriba/discussions): real event experience is what improves the project most.
- Bugs and improvements: [Issues](https://github.com/jubul/transcriba/issues) using the templates. Those labeled `good first issue` are a good entry point.
- Vulnerabilities: private report as described in [SECURITY.md](SECURITY.md).
- We follow the [Code of Conduct](CODE_OF_CONDUCT.md) (Contributor Covenant 2.1).

## License

Apache License 2.0. Made so that open source conferences can be accessible.
