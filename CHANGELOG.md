# Historial de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.1.0/); versiones según [SemVer](https://semver.org/lang/es/).

## [Sin publicar]

## [0.1.0] - 2026-09-24

Primera versión.

- Motores `gemini-live` (transcripción en streaming + traducción con contexto), `gemini-live-translate`, `gemini-chunked`, `local` (faster-whisper + Gemma vía Ollama) y `mock`.
- Fuentes de audio: navegador (`/ingest`), RTMP/SRT/HLS, dispositivos de captura y archivos, todo vía ffmpeg.
- Varias salas en paralelo en un proceso; creación en caliente desde el panel con persistencia.
- Vista de audiencia, visor (celular, pantalla, overlay OBS), panel de operación, QR por sala.
- Exportación SRT/VTT/TXT/JSONL.
- Asistente `transcriba init`, carga automática de `.env`, perfiles de latencia.
- Documentación: operación para conferencias, referencia de configuración generada, latencia, costos, API, arquitectura.
