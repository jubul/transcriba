# transcriba

[![CI](https://github.com/jubul/transcriba/actions/workflows/ci.yml/badge.svg)](https://github.com/jubul/transcriba/actions/workflows/ci.yml) [![Licencia Apache-2.0](https://img.shields.io/badge/licencia-Apache--2.0-blue.svg)](LICENSE) [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab.svg)](pyproject.toml) [![Código de conducta](https://img.shields.io/badge/c%C3%B3digo%20de%20conducta-Contributor%20Covenant%202.1-5e0d73.svg)](docs/es/CODIGO_DE_CONDUCTA.md)

**Subtítulos en vivo para conferencias, a escala y open source.** Toma el audio de cada escenario y produce subtítulos en tiempo real en el idioma original y traducidos (inglés → español, español → inglés, o el par que necesites), para 5, 10 o 30 salas en paralelo. La audiencia elige sala e idioma desde el celular; la sala los muestra en pantalla o como overlay en el streaming.

Construido sobre las capacidades de audio de **Gemini** (Live API) y con un camino **100 % local** con **Whisper + Gemma** vía Ollama. Licencia Apache-2.0. [Read this in English](README.md).

```
audio de la sala ─► transcriba ─► "…and that's why context propagation matters."   (< 1 s)
                                  "…y por eso importa la propagación de contexto."  (~2-3 s)
```

| Documento | Para qué |
|---|---|
| Este README | Qué es, instalación en 5 minutos, conceptos |
| [docs/es/OPERACION.md](docs/es/OPERACION.md) | Runbook para desplegar y operar en una conferencia (servidor, captura por sala, día del evento, exportación) |
| [docs/es/CONFIGURACION.md](docs/es/CONFIGURACION.md) | Referencia de cada opción del YAML (generada desde el código) |
| [docs/es/LATENCIA.md](docs/es/LATENCIA.md) | De qué depende la velocidad y cómo ajustarla |
| [docs/es/COSTOS.md](docs/es/COSTOS.md) | Precios por modelo y costo estimado por hora de sala y por evento |
| [docs/es/API.md](docs/es/API.md) | REST y WebSockets para integrar otros visores o sistemas |
| [docs/es/ARQUITECTURA.md](docs/es/ARQUITECTURA.md) | Cómo está hecho y por qué |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Entorno de desarrollo, tests, cómo agregar un motor (en inglés) |
| [CHANGELOG.md](CHANGELOG.md) · [SECURITY.md](SECURITY.md) · [CODE_OF_CONDUCT.md](docs/es/CODIGO_DE_CONDUCTA.md) | Versiones, reporte de vulnerabilidades, convivencia |

## Qué resuelve

| Necesidad | Cómo |
|---|---|
| Audio en vivo → subtítulos en tiempo real | Streaming al Live API de Gemini (`gemini-3.5-transcribe-live`): hipótesis parciales en menos de un segundo, frases finales al terminar cada oración, traducción de cada frase con contexto y glosario en ~1 s. |
| Idioma original + español (y español → inglés) | Cualquier par de idiomas por sala. Con `source_language: auto` y `target_languages: [es, en]` cada frase se traduce al otro idioma, sea cual sea el hablado. |
| Varias sesiones en paralelo | Un proceso maneja decenas de salas. Cada sala tiene su fuente de audio, motor, idiomas y glosario; se crean, inician y paran desde el panel sin tocar las demás. |
| Licencia OSI y guía de despliegue | Apache-2.0 y un runbook pensado para voluntarios de cualquier conferencia. |
| Vista para la audiencia | La página principal lista las salas en vivo; cada persona elige idioma y lo lee en su teléfono. El mismo visor sirve para la pantalla de la sala y como overlay transparente en OBS. QR por sala. |

## Inicio en 5 minutos

Requisitos: Python 3.10 o superior y `ffmpeg` en el PATH (`apt install ffmpeg`, `brew install ffmpeg`, o el instalador de Windows).

```bash
git clone https://github.com/jubul/transcriba && cd transcriba
python3 -m venv .venv && source .venv/bin/activate        # con uv: uv venv --python 3.12 && source .venv/bin/activate
pip install -e .                                            # con uv: uv pip install -e .

transcriba init        # asistente: nombre del evento, API key, idiomas, cantidad de salas → transcriba.yaml + .env
transcriba check       # verifica ffmpeg, credenciales, modelos
transcriba serve       # levanta todo e imprime las URLs
```

`transcriba init` pide la API key de Gemini (se crea en [aistudio.google.com/apikey](https://aistudio.google.com/apikey); los créditos de Google Developers aplican ahí), genera un token de administración y crea una sala por escenario. El `.env` resultante se carga solo cada vez que arrancás: no hay que exportar variables.

Al arrancar, `serve` muestra las tres URLs que importan:

- **Audiencia**: `http://<ip>:8000/` para elegir sala e idioma.
- **Panel**: `http://<ip>:8000/admin` para operar (pide el token del `.env`).
- **Ingesta**: `http://<ip>:8000/ingest/<sala>` para mandar el audio desde la laptop de cada sala.

Sin credenciales ni audio real, hay una demo completa: `transcriba serve -c config/demo.yaml` (token `demo`).

Con Docker: `cp .env.example .env`, editarlo, `docker compose up -d`. Perfiles opcionales: `--profile rtmp` levanta un servidor RTMP para recibir OBS; `--profile local` levanta Ollama.

## Probarlo con tu micrófono

```bash
transcriba serve -c config/mic.yaml
```
Abrí `http://localhost:8000/ingest/mic?token=mic`, apretá "Empezar a enviar" y aceptá el permiso del micrófono. En otra pestaña, `http://localhost:8000/view/mic?lang=both`. Hablá en español o en inglés: primero aparece lo que dijiste y uno o dos segundos después la traducción. En WSL2 también funciona directo desde la terminal con el micrófono de Windows: `transcriba run pulse:default -e gemini-live -l es -t en`.

## Cómo llega el audio

El campo `source` de cada sala acepta:

| `source` | Caso típico |
|---|---|
| `browser` | Una laptop al lado de la consola abre `/ingest/<sala>` y manda el audio desde el navegador (micrófono, interfaz USB o audio del sistema). Reconecta sola si se cae el wifi. |
| `rtmp://…`, `srt://…`, `https://…/x.m3u8` | Tomar el audio del streaming: OBS o vMix hacen push a un nginx-rtmp (incluido en el compose). |
| `pulse:default`, `alsa:hw:1,0`, `avfoundation::0`, `dshow:audio=…` | Dispositivo de captura en la máquina donde corre transcriba (`transcriba devices` los lista). |
| `charla.mp4`, `audio.mp3` | Archivos, reproducidos en tiempo real (`loop: true` para demos). |
| `ffmpeg:<args>` | Cualquier cosa que ffmpeg pueda leer. |

Todo se normaliza a PCM 16 kHz mono; ffmpeg hace el trabajo sucio.

## Motores y costos

Se elige por sala con `engine:`.

| Motor | Qué usa | Latencia | Costo por hora de sala | Cuándo |
|---|---|---|---|---|
| `gemini-live` (recomendado) | `gemini-3.5-transcribe-live` (ASR en streaming, vocabulario personalizado) + `gemini-3.5-flash-lite` (traducción con contexto) | original < 1 s, traducción +1-2 s | ≈ US$ 0.70 | Producción. N idiomas destino. |
| `gemini-live-translate` | `gemini-3.5-live-translate-preview`: un solo modelo, voz → voz traducida + transcripciones | 2-4 s | ≈ US$ 2.20 | Además de subtítulos querés audio traducido para auriculares (botón 🔊 en el visor). Experimental. |
| `gemini-chunked` | VAD local → clips WAV → `gemini-3.5-flash-lite` transcribe y traduce en una llamada | 3-8 s | ≈ US$ 0.20 | Económico, funciona con el free tier, sin WebSockets. |
| `local` | `faster-whisper` (ASR) + Gemma 4 en Ollama (traducción) | 3-8 s | US$ 0 + GPU | Sin nube. Una GPU de escritorio maneja 3-5 salas. |
| `mock` | VAD real, texto ficticio | — | 0 | Demos, tests, ensayo de la operación. |

Nerdearla (30 charlas × 45 min ≈ 22.5 horas de sala) cuesta **≈ US$ 16 con `gemini-live`**, dentro de los US$ 25 de crédito. Las sesiones Live solo se abren mientras llega audio, así que una sala esperando su ingesta no gasta. Detalle en [docs/es/COSTOS.md](docs/es/COSTOS.md).

## Latencia

La velocidad depende poco del modelo y mucho de **cuándo se da por terminada una frase**: el modelo espera una pausa, transcriba espera que el trozo cierre una oración, y recién entonces traduce. El texto original aparece mientras el orador habla; la traducción, uno o dos segundos después de la pausa. Un solo ajuste lo regula:

```yaml
latency_profile: fast      # frases más cortas y rápidas
latency_profile: balanced  # por defecto
latency_profile: quality   # frases completas, mejor traducción
```

También `transcriba run … --latency fast` para comparar en la terminal. Qué mueve cada perfil y cómo afinar a mano: [docs/es/LATENCIA.md](docs/es/LATENCIA.md).

## Configuración

Un YAML, generado por `transcriba init` y editable a mano ([ejemplo completo](config/transcriba.example.yaml), [referencia de todas las claves](docs/es/CONFIGURACION.md)):

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
  - { id: sala-a, name: "Sala A · Keynotes", source: rtmp://localhost/live/sala-a }
  - { id: sala-b, name: "Sala B · Workshops", source: browser, source_language: auto, target_languages: [es, en] }
  - { id: sala-c, name: "Sala C", source: pulse:default, engine: local, source_language: es, target_languages: [en],
      translator: { provider: ollama, model: "gemma4:e4b" } }
```

Las claves desconocidas son un error, así un typo no pasa desapercibido. Las salas creadas desde el panel se guardan en `data/sessions.json` y vuelven al reiniciar.

## Vistas

- **`/`** audiencia: salas en vivo con un botón por idioma. Funciona en cualquier celular.
- **`/view/<sala>?lang=es`** visor. Parámetros: `lang=orig|es|both|…`, `size=1.4`, `lines=2`, `theme=light`, `history=1` (transcripción completa con tiempos), `overlay=1` (fondo transparente para la fuente "Navegador" de OBS). El engranaje ⚙︎ cambia todo en vivo, copia el enlace y muestra el QR.
- **`/admin`** operación: estado, nivel de audio, subtítulos emitidos, personas viendo, últimos textos, detalles y errores del motor; crear, iniciar, parar y borrar salas; enlaces a visor, overlay, ingesta, QR y exportación SRT/TXT.
- **`/ingest/<sala>`** ingesta desde el navegador: elegís el dispositivo, ves el nivel, y la página explica cualquier problema (token, permisos, sesión detenida).

## Operar varias salas

Cada sala es una sesión independiente dentro del mismo proceso. Se definen en el YAML o se crean en caliente desde el panel (o con `POST /api/sessions`). Parar o reiniciar una no afecta a las otras, y las transcripciones se agregan al JSONL de cada sala sin borrarse. Para el día del evento, el runbook está en [docs/es/OPERACION.md](docs/es/OPERACION.md): qué cablear, qué mirar en el panel, qué hacer si algo falla y cómo exportar al final.

Un proceso alcanza para decenas de salas con motores en la nube. Para más, o por redundancia, se levantan varios procesos (uno por track o edificio) detrás de un reverse proxy.

## 100 % local

```bash
pip install -e ".[local]"          # faster-whisper; ".[cuda]" agrega las libs NVIDIA para GPU
ollama pull gemma4:e4b              # o gemma4:12b si hay VRAM
```
En la sala: `engine: local` con `translator: { provider: ollama, model: gemma4:e4b }`. Whisper corre en GPU si hay CUDA y cae a CPU si faltan librerías. Gemma 4 E2B/E4B entienden audio de forma nativa; un motor Gemma-audio puro es el siguiente paso natural.

## API

REST y WebSockets documentados en [docs/es/API.md](docs/es/API.md). Cada subtítulo tiene `id` estable, `seq`, `status` (`partial` → `final` → `translated`), `original`, `language`, `translations`, `t_start`/`t_end`. Los clientes hacen *upsert* por `id`, así que construir otro visor (una app, un LED wall) son unas decenas de líneas.

## Desarrollo

```bash
pip install -e ".[dev,local]"
pytest -q                                      # 37 tests
python scripts/gen_config_reference.py         # regenera docs/es/CONFIGURACION.md desde los modelos
transcriba run samples/jfk.wav -e mock --no-realtime
```
Guía en [CONTRIBUTING.md](CONTRIBUTING.md).

## Estado y limitaciones

- Probado con audio real de micrófono contra el Live API (`gemini-live`): parciales, finales y traducción funcionan. La rotación de sesiones a los 9 minutos está probada contra un Live API simulado; falta observarla en una charla completa.
- Los modelos Live limitan cada sesión a ~10 min: transcriba rota en una pausa del orador; en el peor caso se puede perder una frase corta en la rotación.
- `gemini-live-translate` empareja original y traducción por orden de llegada (experimental).
- El VAD por energía es simple a propósito; en salas muy ruidosas ajustar `vad.speech_threshold_db` o usar `gemini-live` (usa el VAD del modelo).
- Sin base de datos: el estado vive en el proceso y en `data/<sala>/captions.jsonl` + `data/sessions.json`.

## Roadmap

- Motor Gemma-audio puro (Gemma 4 E4B) por Transformers u Ollama: transcripción y traducción local en un solo modelo.
- Corrección retroactiva de subtítulos con contexto largo.
- Publicación automática de transcripciones al cierre de cada charla (Markdown/HTML).
- Métricas Prometheus por sala (latencia, tokens, errores).

## Comunidad

- ¿Lo usaste o lo querés usar en tu conferencia? Contalo en [Discussions](https://github.com/jubul/transcriba/discussions): las experiencias reales de eventos son lo que más mejora el proyecto.
- Errores y mejoras: [Issues](https://github.com/jubul/transcriba/issues) con las plantillas. Los marcados `good first issue` son un buen punto de entrada.
- Vulnerabilidades: reporte privado según [SECURITY.md](SECURITY.md).
- Nos regimos por el [Código de Conducta](docs/es/CODIGO_DE_CONDUCTA.md) (Contributor Covenant 2.1).
- La documentación principal del proyecto está en inglés; esta es la traducción al español.

## Licencia

Apache License 2.0. Hecho para que las conferencias open source sean accesibles.
