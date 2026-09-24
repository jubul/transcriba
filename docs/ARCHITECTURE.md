# Architecture

🇦🇷 [Versión en español](es/ARQUITECTURA.md)

## Overview

```
   Room A          Room B            Room N
 OBS/mixer       laptop+browser    local device
   │ RTMP/SRT       │ WebSocket        │ pulse/alsa
   ▼                ▼                  ▼
┌───────────────────────────────────────────────────────────────┐
│ transcriba (one asyncio process, N sessions)                   │
│                                                                │
│  Source ──► PCM 16 kHz mono ──► Engine ──► Caption events      │
│  (ffmpeg | push)                 │            │                 │
│                                  │            ▼                 │
│            ┌─────────────────────┘        Hub (pub/sub)         │
│            │ gemini-live: transcribe-live ─┬─► WS /ws/captions  │
│            │              + flash-lite     ├─► WS /ws/status    │
│            │ gemini-live-translate         ├─► WS /ws/audio     │
│            │ gemini-chunked                └─► Store (JSONL)    │
│            │ local: whisper + ollama/gemma        │              │
│            │ mock                                 ▼              │
│            └──────────────────────────  /api/…/transcript.srt   │
└───────────────────────────────────────────────────────────────┘
        ▲ REST/WS admin                 ▼ static HTML
      /admin (operations)    / (audience)  /view/{room} (viewer, OBS overlay)
```

## Components

| Module | Role |
|---|---|
| `audio/source.py` | Audio sources. `FfmpegSource` normalizes any input (file, RTMP/SRT/HLS, pulse/alsa/avfoundation/dshow) to 16 kHz mono s16le PCM in 100 ms chunks and restarts itself if a stream drops. `PushSource` receives audio pushed from the browser. |
| `audio/segmenter.py` | Energy-based VAD with an adaptive noise floor. Cuts at pauses (`min_silence_ms`), enforces a maximum (`max_segment_s`) by cutting at the last detected pause, and discards short bursts. Used by the segment-based engines. `ActivityTracker` only answers "is there silence right now?" so Live sessions rotate at a good moment. |
| `engines/` | An `Engine` receives PCM through `feed()` and emits `Caption`s. Two families: **streaming** (`LiveSessionEngine`: Gemini Live API) and **segment-based** (`SegmentingEngine`: transcribes each utterance). |
| `translators/` | Text translation with context (previous sentences + glossary), JSON output with a schema. `gemini` (Flash-Lite), `ollama` (Gemma), `mock`, `none`. |
| `pipeline.py` | `SessionRunner` wires source + engine + translator, measures level and stream time, publishes status. `SessionManager` runs N runners and persists the rooms created at runtime. |
| `hub.py` | In-memory pub/sub: one queue per subscriber, oldest message dropped when a client is slow; bounded history for late joiners. |
| `store.py` / `export.py` | JSONL persistence per room (`data/<id>/captions.jsonl`) and SRT/VTT/TXT/JSONL exports. |
| `server.py` | FastAPI: pages, REST, WebSockets. Token auth on admin operations and ingest. |
| `web/` | HTML/JS without a build step: audience, viewer, panel, ingest (an AudioWorklet resamples to 16 kHz). |

## Caption model

Every `Caption` has a stable `id` and a monotonic `seq` per room; viewers upsert by `id` and order by `seq`. Lifecycle:

1. `partial`: ASR hypothesis (changes several times per second with `gemini-live`).
2. `final`: definitive original text; translation in progress.
3. `translated`: translations attached (or `meta.translation_error`). Only this state is persisted.

This way the original language shows with sub-second latency and the translation arrives about a second later, without blocking.

If the detected language matches a target language, the "translation" is the original. That is what makes `source_language: auto` with `target_languages: [es, en]` work: whatever is said in English comes out in Spanish and vice versa.

## Recommended engine: `gemini-live`

- `gemini-3.5-transcribe-live` over the Live API: interim results (`interim_input_transcription`) and finals (`input_transcription`, with `finished`), custom vocabulary (the glossary), SMART mode (punctuation, no fillers), fixed or automatic language.
- Translation with `gemini-3.5-flash-lite`, thinking disabled, JSON schema, with the previous 6 sentences as context and per-language style notes (neutral Latin American Spanish by default).
- **Session rotation**: the Live API caps every session (~10 min). `LiveSessionEngine` opens a new one at ~9 min while waiting for a pause of at least 400 ms (or on `go_away`/580 s), sends `audio_stream_end`, drains finals for up to 3 s and continues on the new session; audio queues up meanwhile, nothing is lost.
- **Lazy connection**: the Live session opens with the first audio chunk and closes after `idle_close_s` without audio (breaks, a room waiting for its ingest). The Live API drops idle sessions (code 1008) and each one consumes quota, so an empty room costs nothing.
- **Clean stop**: stopping a room sends the pending audio, `audio_stream_end`, and waits for the last finals before closing.
- Reconnection with exponential backoff on network/quota errors, interruptible by `stop()`.
- **Finals in pieces**: `input_transcription` arrives in parts and `finished` marks the end; transcriba accumulates and commits according to punctuation and two waits (`final_chunk_timeout_s`, `final_chunk_max_wait_s`). See [LATENCY.md](LATENCY.md).

## Scaling

- Everything is I/O: one process handles dozens of rooms (30 rooms ≈ 30 ffmpeg processes + 30 WebSockets + ~10 translation requests/s). The practical limit is the API quota and ffmpeg CPU (minimal).
- For more rooms or high availability: several processes (one per track/building) behind a reverse proxy, each with its own YAML. State is per process; the audience enters by room URL, so splitting by path is trivial.
- `local` engine: the GPU is the bottleneck. Whisper `small` on an RTX 3060 processes ~10× real time → 3-5 rooms per GPU; Gemma 4 E4B for translation adds load. Scale with more machines.

## Decisions and alternatives considered

- **Live API vs. chunks**: streaming gives interim results and better semantic segmentation; chunks are simpler and cheaper. Both are implemented, selectable per room.
- **Separate translation vs. one model**: separating allows N languages, controlled context and glossary, and swapping the translator (local Gemma) without touching the ASR. `gemini-live-translate` exists as the single-model alternative (and yields translated audio).
- **Energy VAD instead of Silero/WebRTC**: no native dependencies or model downloads; stage audio has a stable noise floor. Swappable in `audio/segmenter.py`.
- **No database**: JSONL per room + `sessions.json` for rooms created on the fly + memory. Enough for an event; easy to back up and publish.
- **Latency profiles** (`latency_profile`) rather than only exposing loose parameters: hand-written values always win over the preset (detected with pydantic's `model_fields_set`).
- **Strict configuration**: unknown keys fail at load time; every field has a description and the reference is generated from the models (`scripts/gen_config_reference.py`).
- **No-build frontend**: a conference deploys it by copying files; no Node or bundlers.
