# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

- English is now the default language of the README and documentation; Spanish versions live in `README.es.md` and `docs/es/`.

## [0.1.0] - 2026-09-24

First release.

- Engines `gemini-live` (streaming transcription + translation with context), `gemini-live-translate`, `gemini-chunked`, `local` (faster-whisper + Gemma via Ollama) and `mock`.
- Audio sources: browser (`/ingest`), RTMP/SRT/HLS, capture devices and files, all through ffmpeg.
- Many rooms in parallel in one process; rooms created live from the panel are persisted.
- Audience page, viewer (phone, screen, OBS overlay), operations panel, QR per room.
- SRT/VTT/TXT/JSONL exports.
- `transcriba init` wizard, automatic `.env` loading, latency profiles.
- Documentation: conference operations, generated configuration reference, latency, costs, API, architecture.
