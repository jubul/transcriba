# Arquitectura

🇬🇧 [English version](../ARCHITECTURE.md)

## Vista general

```
   Sala A          Sala B            Sala N
 OBS/consola     laptop+navegador   dispositivo local
   │ RTMP/SRT       │ WebSocket        │ pulse/alsa
   ▼                ▼                  ▼
┌───────────────────────────────────────────────────────────────┐
│ transcriba (un proceso asyncio, N sesiones)                    │
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
        ▲ REST/WS admin                 ▼ HTML estático
      /admin (operación)     / (audiencia)  /view/{sala} (visor, overlay OBS)
```

## Componentes

| Módulo | Rol |
|---|---|
| `audio/source.py` | Fuentes de audio. `FfmpegSource` normaliza cualquier entrada (archivo, RTMP/SRT/HLS, pulse/alsa/avfoundation/dshow) a PCM s16le 16 kHz mono en chunks de 100 ms; se reinicia solo si el stream cae. `PushSource` recibe audio del navegador. |
| `audio/segmenter.py` | VAD por energía con piso de ruido adaptativo. Corta en pausas (`min_silence_ms`), con máximo (`max_segment_s`) buscando la última pausa, y descarta ráfagas cortas. Lo usan los motores por segmentos. `ActivityTracker` solo detecta "hay silencio ahora" para rotar sesiones Live en un buen momento. |
| `engines/` | Un `Engine` recibe PCM con `feed()` y emite `Caption`s. Dos familias: **streaming** (`LiveSessionEngine`: Gemini Live API) y **por segmentos** (`SegmentingEngine`: transcribe cada utterance). |
| `translators/` | Traducción de texto con contexto (frases previas + glosario), salida JSON con schema. `gemini` (Flash-Lite), `ollama` (Gemma), `mock`, `none`. |
| `pipeline.py` | `SessionRunner` une fuente + motor + traductor, mide nivel y tiempo de stream, publica estado. `SessionManager` administra N runners. |
| `hub.py` | Pub/sub en memoria: colas por suscriptor con descarte del más viejo si el cliente es lento; historial acotado para quien entra tarde. |
| `store.py` / `export.py` | Persistencia JSONL por sesión (`data/<id>/captions.jsonl`) y exportación SRT/VTT/TXT/JSONL. |
| `server.py` | FastAPI: páginas, REST, WebSockets. Auth por token en operaciones de administración e ingesta. |
| `web/` | HTML/JS sin build: audiencia, visor, panel, ingesta (AudioWorklet que remuestrea a 16 kHz). |

## Modelo de subtítulo

Cada `Caption` tiene `id` estable y `seq` monótono por sesión; los visores hacen *upsert* por `id` y ordenan por `seq`. Ciclo de vida:

1. `partial`: hipótesis del ASR (cambia varias veces por segundo con `gemini-live`).
2. `final`: texto original definitivo; traducción en curso.
3. `translated`: traducciones adjuntas (o `meta.translation_error`). Solo este estado se persiste.

Así el idioma original aparece con latencia sub-segundo y la traducción llega ~1 s después, sin bloquear.

Si el idioma detectado coincide con un idioma destino, la "traducción" es el original (permite `source_language: auto` con `target_languages: [es, en]`: lo que se dice en inglés sale en español y viceversa).

## Motor recomendado: `gemini-live`

- `gemini-3.5-transcribe-live` por Live API: parciales (`interim_input_transcription`) y finales (`input_transcription`, con `finished`), vocabulario personalizado (el glosario), modo SMART (puntuación, sin muletillas), idioma fijo o auto.
- Traducción con `gemini-3.5-flash-lite`, thinking desactivado, JSON schema, con las 6 frases previas como contexto y notas de estilo por idioma (español neutro latinoamericano por defecto).
- **Rotación de sesión**: el Live API limita cada sesión (~10 min). `LiveSessionEngine` abre otra a los ~9 min esperando una pausa de ≥400 ms (o al llegar `go_away`/580 s), manda `audio_stream_end`, drena finales hasta 3 s y sigue con la nueva; el audio se encola mientras tanto, no se pierde.
- **Conexión perezosa**: la sesión Live se abre con el primer chunk de audio y se cierra tras `idle_close_s` sin audio (recesos, sala esperando su ingesta). El Live API corta las sesiones ociosas (código 1008) y cada una cuesta cuota; así una sala vacía no cuesta nada.
- **Parada limpia**: al detener una sala se envía el audio pendiente, `audio_stream_end`, y se esperan los últimos finales antes de cerrar.
- Reconexión con backoff exponencial ante errores de red/cuota, interrumpible por `stop()`.
- **Finales en trozos**: `input_transcription` llega por partes y `finished` marca el fin; transcriba acumula y confirma según puntuación y dos esperas (`final_chunk_timeout_s`, `final_chunk_max_wait_s`). Ver [LATENCIA.md](LATENCIA.md).

## Escalado

- Todo es I/O: un proceso maneja decenas de salas (30 salas ≈ 30 ffmpeg + 30 WebSockets + ~10 req/s de traducción). Límite práctico: cuota de la API y CPU de ffmpeg (mínima).
- Para más salas o alta disponibilidad: varios procesos (uno por track/edificio) detrás de un reverse proxy, cada uno con su YAML. El estado es por proceso; la audiencia entra por URL de sala, así que el reparto por path es trivial.
- Motor `local`: el cuello de botella es la GPU. Whisper `small` en una RTX 3060 procesa ~10× tiempo real → 3-5 salas por GPU; Gemma 4 E4B para traducir agrega carga. Escalar con más máquinas.

## Decisiones y alternativas consideradas

- **Live API vs. fragmentos**: el streaming da parciales y mejor segmentación semántica; los fragmentos son más simples y baratos. Se implementaron ambos, elegible por sesión.
- **Traducir aparte vs. en el mismo modelo**: separar permite N idiomas, contexto y glosario controlados, y cambiar el traductor (Gemma local) sin tocar el ASR. `gemini-live-translate` existe como alternativa de un solo modelo (y da audio traducido).
- **VAD por energía en vez de Silero/WebRTC**: sin dependencias nativas ni modelos; el audio de escenario tiene piso de ruido estable. Intercambiable en `audio/segmenter.py`.
- **Sin base de datos**: JSONL por sesión + `sessions.json` para las salas creadas en caliente + memoria. Suficiente para un evento; fácil de respaldar y publicar.
- **Perfiles de latencia** (`latency_profile`) en vez de exponer solo parámetros sueltos: los valores escritos a mano siempre ganan sobre el preset (se detecta con `model_fields_set` de pydantic).
- **Configuración estricta**: claves desconocidas fallan al cargar; cada campo tiene descripción y la referencia se genera desde los modelos (`scripts/gen_config_reference.py`).
- **Frontend sin build**: una conferencia lo despliega copiando archivos; sin Node ni bundlers.
