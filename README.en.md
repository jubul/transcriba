# transcriba

**Live captions for conferences, at scale, open source.** Takes the audio of every stage and produces real-time subtitles in the original language and translated (English → Spanish, Spanish → English, or any pair), for 5, 10 or 30 rooms in parallel. Attendees pick a room and a language on their phone; the room shows them on screen or as an overlay on the stream.

Built on **Gemini**'s audio capabilities (Live API), with a **fully local** path using **Whisper + Gemma** through Ollama. Apache-2.0. The detailed documentation is in Spanish ([README.md](README.md), [docs/](docs/)); this page covers what you need to get running.

```
stage audio ─► transcriba ─► "…and that's why context propagation matters."   (< 1 s)
                             "…y por eso importa la propagación de contexto."  (~2-3 s)
```

## What it does

- **Streaming transcription** with `gemini-3.5-transcribe-live`: interim hypotheses in under a second, final sentences at each pause, custom vocabulary from your glossary.
- **Translation with context** with `gemini-3.5-flash-lite`: each sentence, with the previous ones as context and your glossary untouched. Any number of target languages. `source_language: auto` with `target_languages: [es, en]` translates each sentence into the other language.
- **Many rooms, one process**: each room has its own audio source, engine, languages and glossary. Create, start and stop rooms from the panel without touching the others.
- **Audience site**: `/` lists live rooms with one button per language; `/view/<room>` works on phones, room screens and as a transparent OBS browser-source overlay. QR code per room.
- **Alternative engines**: `gemini-live-translate` (single model, also outputs translated audio), `gemini-chunked` (cheap, free-tier friendly), `local` (faster-whisper + Gemma 4 via Ollama, no cloud), `mock` (demos).
- **Exports**: SRT, WebVTT, TXT, JSONL per room.

## Quick start

Requirements: Python 3.10+ and `ffmpeg` on the PATH.

```bash
git clone https://github.com/<your-org>/transcriba && cd transcriba
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

transcriba init      # wizard: event name, Gemini API key, languages, number of rooms → transcriba.yaml + .env
transcriba check     # verifies ffmpeg, credentials and models
transcriba serve     # starts everything and prints the URLs
```

Get an API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). The generated `.env` is loaded automatically on every start. `serve` prints the audience URL (`/`), the operator panel (`/admin`, asks for the admin token from `.env`) and one ingest URL per room (`/ingest/<room>`, open it on the laptop next to the mixing desk and press start).

No credentials? `transcriba serve -c config/demo.yaml` runs a full demo with a mock engine (token `demo`). Docker: `cp .env.example .env`, edit, `docker compose up -d` (`--profile rtmp` adds an RTMP server for OBS, `--profile local` adds Ollama).

## Audio sources

| `source` | Use |
|---|---|
| `browser` | A laptop opens `/ingest/<room>` and streams mic / USB interface / system audio from the browser. Auto-reconnects. |
| `rtmp://…`, `srt://…`, `https://…/x.m3u8` | Take the audio from your streaming setup (OBS/vMix push to the bundled nginx-rtmp). |
| `pulse:default`, `alsa:hw:1,0`, `avfoundation::0`, `dshow:audio=…` | Capture device on the machine running transcriba (`transcriba devices`). |
| `talk.mp4`, `audio.mp3` | Files, played in real time (`loop: true` for demos). |
| `ffmpeg:<args>` | Anything ffmpeg can read. |

## Engines and cost

| Engine | Latency | Cost per room-hour | Notes |
|---|---|---|---|
| `gemini-live` (recommended) | original < 1 s, translation +1-2 s | ≈ US$ 0.70 | N target languages |
| `gemini-live-translate` | 2-4 s | ≈ US$ 2.20 | also streams translated audio (🔊 in the viewer); experimental |
| `gemini-chunked` | 3-8 s | ≈ US$ 0.20 | free-tier friendly, no WebSockets |
| `local` | 3-8 s | US$ 0 + GPU | faster-whisper + Gemma 4 (Ollama); 3-5 rooms per desktop GPU |

A 30-talk conference (≈ 22.5 room-hours) costs about US$ 16 with `gemini-live`. Live sessions are only open while audio flows, so idle rooms cost nothing.

## Latency

Speed depends less on the model than on **when a sentence is considered finished**: the model waits for a pause, transcriba waits for the chunk to close a sentence, then translates. Original text shows while the speaker talks; the translation follows one or two seconds after the pause. One knob:

```yaml
latency_profile: fast | balanced | quality
```
`fast` gives shorter, quicker sentences; `quality` gives complete sentences and better translations. Fine-tuning in [docs/LATENCIA.md](docs/LATENCIA.md) (Spanish).

## Configuration

```yaml
latency_profile: balanced
server: { title: "My conference", admin_token: ${TRANSCRIBA_ADMIN_TOKEN}, public_url: https://subs.example.org }
gemini: { api_key: ${GEMINI_API_KEY} }
defaults: { engine: gemini-live, source_language: en, target_languages: [es], glossary: [Kubernetes, OpenTelemetry] }
sessions:
  - { id: room-a, name: "Room A · Keynotes", source: rtmp://localhost/live/room-a }
  - { id: room-b, name: "Room B", source: browser, source_language: auto, target_languages: [es, en] }
  - { id: room-c, name: "Room C (offline)", source: pulse:default, engine: local, source_language: es, target_languages: [en],
      translator: { provider: ollama, model: "gemma4:e4b" } }
```
Unknown keys are errors. Every option is documented in [docs/CONFIGURACION.md](docs/CONFIGURACION.md) (generated from the code). Rooms created from the panel persist in `data/sessions.json`.

## API

REST: `GET/POST /api/sessions`, `POST /api/sessions/{id}/start|stop`, `DELETE /api/sessions/{id}`, `GET /api/sessions/{id}/captions`, `GET /api/sessions/{id}/transcript.{srt|vtt|txt|jsonl}?lang=es`, `GET /api/sessions/{id}/qr.svg`. Admin calls need `X-Admin-Token`.
WebSockets: `/ws/captions/{id}` (history + `caption`/`status` events), `/ws/status`, `/ws/audio/{id}` (translated PCM 24 kHz), `/ws/ingest/{id}?token=` (PCM 16 kHz in).
Captions have a stable `id`, a `seq`, a `status` (`partial` → `final` → `translated`), `original`, `language`, `translations`, `t_start`/`t_end`. Clients upsert by `id`. Details: [docs/API.md](docs/API.md).

## Development

```bash
pip install -e ".[dev,local]"
pytest -q                                 # 37 tests, including a fake Live API for rotation/drain/reconnect
python scripts/gen_config_reference.py    # regenerate the config reference
```
See [CONTRIBUTING.md](CONTRIBUTING.md). License: Apache-2.0.
