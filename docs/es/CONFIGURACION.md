# Referencia de configuración

🇬🇧 [English version](../CONFIGURATION.md)

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


## AppConfig

Raíz del archivo de configuración.

| Clave | Tipo | Default | Descripción |
|---|---|---|---|
| `latency_profile` | `fast` \| `balanced` \| `quality` | `balanced` | fast = frases cortas y rápidas; balanced = equilibrio; quality = frases completas, mejor traducción. Ajusta los parámetros de latencia que no estén fijados a mano (docs/LATENCIA.md). |
| `server` | [ServerConfig](#serverconfig) | (sección) | Servidor web. |
| `gemini` | [GeminiConfig](#geminiconfig) | (sección) | Credenciales de Gemini. |
| `engines` | [EnginesConfig](#enginesconfig) | (sección) | Ajustes por motor. |
| `translator` | [TranslatorConfig](#translatorconfig) | (sección) | Traductor de texto global. |
| `defaults` | [SessionDefaults](#sessiondefaults) | (sección) | Valores por defecto de las salas. |
| `sessions` | lista de [SessionConfig](#sessionconfig) | `[]` | Salas. También se pueden crear en caliente desde el panel (se persisten en data_dir/sessions.json). |

## ServerConfig

Servidor web: puertos, autenticación, persistencia.

| Clave | Tipo | Default | Descripción |
|---|---|---|---|
| `title` | texto | `Subtítulos en vivo` | Título que ve la audiencia en la página principal. |
| `host` | texto | `0.0.0.0` | Interfaz donde escucha el servidor. 0.0.0.0 = todas. |
| `port` | entero | `8000` | Puerto HTTP/WebSocket. |
| `admin_token` | texto | `""` | Token para el panel, la API de administración y la ingesta. Vacío = sin autenticación (solo para pruebas locales). |
| `public_url` | texto | `""` | URL pública (https://subs.mievento.org) usada en los QR y en el banner. Vacío = la URL con la que entra cada cliente. |
| `data_dir` | texto | `data` | Directorio de persistencia: transcripciones JSONL por sala y sesiones creadas desde el panel. |
| `cors_origins` | lista de texto | `['*']` | Orígenes permitidos para CORS (si otro sitio consume la API). |
| `history_size` | entero | `200` | Subtítulos recientes que recibe un visor al conectarse. |

## GeminiConfig

Credenciales de Gemini (API key de AI Studio o Vertex AI).

| Clave | Tipo | Default | Descripción |
|---|---|---|---|
| `api_key` | texto | `""` | API key de Google AI Studio. Vacío = usar GEMINI_API_KEY o GOOGLE_API_KEY del entorno. |
| `vertexai` | booleano | `False` | Usar Vertex AI (credenciales de Google Cloud) en lugar de API key. |
| `project` | texto | `""` | Proyecto de Google Cloud (solo Vertex AI). |
| `location` | texto | `""` | Región de Vertex AI, por ejemplo us-central1. |

## EnginesConfig

Ajustes de cada motor. Solo hace falta tocar el que se usa.

| Clave | Tipo | Default | Descripción |
|---|---|---|---|
| `gemini-live` | [GeminiLiveConfig](#geminiliveconfig) | (sección) | Ajustes del motor gemini-live. |
| `gemini-live-translate` | [GeminiLiveTranslateConfig](#geminilivetranslateconfig) | (sección) | Ajustes del motor gemini-live-translate. |
| `gemini-chunked` | [GeminiChunkedConfig](#geminichunkedconfig) | (sección) | Ajustes del motor gemini-chunked. |
| `local` | [LocalConfig](#localconfig) | (sección) | Ajustes del motor local. |

## GeminiLiveConfig

Motor `gemini-live`: transcripción en streaming + traductor de texto. Hereda el ciclo de vida de sesiones Live (rotación, drenaje, inactividad).

| Clave | Tipo | Default | Descripción |
|---|---|---|---|
| `rotate_after_s` | número | `540.0` | Desde este momento se busca una pausa del orador para abrir una sesión nueva. |
| `rotate_deadline_s` | número | `580.0` | Se rota sí o sí al llegar aquí, aunque el orador siga hablando. |
| `rotate_quiet_ms` | entero | `400` | Cuánto silencio cuenta como pausa para rotar. |
| `drain_timeout_s` | número | `3.0` | Espera máxima de los últimos finales al rotar o detener. |
| `idle_close_s` | número | `30.0` | Sin audio durante este tiempo se cierra la sesión Live; se reabre sola al volver el audio. |
| `reconnect_backoff_s` | número | `1.0` | Espera inicial antes de reconectar tras un error. |
| `reconnect_backoff_max_s` | número | `20.0` | Espera máxima entre reintentos (crece exponencialmente). |
| `asr_model` | texto | `gemini-3.5-transcribe-live` | Modelo de transcripción en streaming del Live API. |
| `mode` | `VERBATIM` \| `SMART` | `SMART` | SMART = puntuación y sin muletillas (mejor para subtítulos); VERBATIM = literal. |
| `emit_partials` | booleano | `True` | Mostrar hipótesis parciales mientras el orador habla (latencia sub-segundo en el idioma original). |
| `start_sensitivity` | `default` \| `high` \| `low` | `default` | Sensibilidad del inicio de voz del VAD del modelo. |
| `end_sensitivity` | `default` \| `high` \| `low` | `default` | Sensibilidad del fin de voz: high cierra frases antes (más rápido, más cortas). |
| `silence_duration_ms` | entero \| null | vacío | Silencio que el modelo considera fin de frase. Vacío = valor del modelo. |
| `prefix_padding_ms` | entero \| null | vacío | Audio previo que el modelo conserva al detectar inicio de voz. Vacío = valor del modelo. |
| `final_chunk_timeout_s` | número | `1.5` | Los finales llegan en trozos: si el trozo termina una oración, se confirma tras esta espera sin novedades. |
| `final_chunk_max_wait_s` | número | `4.0` | Si el trozo quedó a mitad de oración, se espera hasta esto por el resto antes de confirmar. |

## GeminiLiveTranslateConfig

Motor `gemini-live-translate`: un solo modelo, voz → voz traducida + transcripciones.

| Clave | Tipo | Default | Descripción |
|---|---|---|---|
| `rotate_after_s` | número | `540.0` | Desde este momento se busca una pausa del orador para abrir una sesión nueva. |
| `rotate_deadline_s` | número | `580.0` | Se rota sí o sí al llegar aquí, aunque el orador siga hablando. |
| `rotate_quiet_ms` | entero | `400` | Cuánto silencio cuenta como pausa para rotar. |
| `drain_timeout_s` | número | `3.0` | Espera máxima de los últimos finales al rotar o detener. |
| `idle_close_s` | número | `30.0` | Sin audio durante este tiempo se cierra la sesión Live; se reabre sola al volver el audio. |
| `reconnect_backoff_s` | número | `1.0` | Espera inicial antes de reconectar tras un error. |
| `reconnect_backoff_max_s` | número | `20.0` | Espera máxima entre reintentos (crece exponencialmente). |
| `model` | texto | `gemini-3.5-live-translate-preview` | Modelo de traducción en vivo del Live API. |
| `echo_target_language` | booleano | `True` | Si el orador ya habla en el idioma destino, pasar su voz/texto sin traducir. |
| `stream_audio` | booleano | `True` | Retransmitir el audio traducido (PCM 24 kHz) por /ws/audio/<sala> para escucharlo en el visor. |

## GeminiChunkedConfig

Motor `gemini-chunked`: segmentos WAV → generate_content (transcribe y traduce en una llamada).

| Clave | Tipo | Default | Descripción |
|---|---|---|---|
| `model` | texto | `gemini-3.5-flash-lite` | Modelo multimodal que recibe el audio. |
| `vad` | [VadConfig](#vadconfig) | (sección) | Segmentación por energía. |
| `max_inflight` | entero | `2` | Segmentos procesándose en paralelo por sala. |
| `timeout_s` | número | `20.0` | Timeout por llamada. |

## VadConfig

Detector de actividad de voz por energía, usado por los motores por segmentos (gemini-chunked, local, mock).

| Clave | Tipo | Default | Descripción |
|---|---|---|---|
| `frame_ms` | entero | `30` | Tamaño de la ventana de análisis en ms. |
| `min_silence_ms` | entero | `600` | Silencio necesario para cerrar una frase. Menos = frases más cortas y rápidas. |
| `min_segment_s` | número | `1.0` | Duración mínima de un segmento antes de cerrarlo por silencio. |
| `max_segment_s` | número | `8.0` | Duración máxima; al llegar se corta en la última pausa detectada. |
| `pre_roll_ms` | entero | `240` | Audio previo al inicio de voz que se incluye para no cortar la primera sílaba. |
| `speech_threshold_db` | número | `10.0` | dB por encima del piso de ruido adaptativo para considerar voz. |
| `min_speech_dbfs` | número | `-55.0` | Nivel absoluto mínimo (dBFS) para considerar voz. |
| `min_speech_ms` | entero | `300` | Segmentos con menos voz que esto se descartan (ruidos, aplausos cortos). |

## LocalConfig

Motor `local`: faster-whisper para transcribir + Ollama (Gemma) para traducir.

| Clave | Tipo | Default | Descripción |
|---|---|---|---|
| `whisper_model` | texto | `small` | Tamaño de Whisper: tiny \| base \| small \| medium \| large-v3 \| large-v3-turbo \| distil-large-v3. |
| `device` | texto | `auto` | auto (GPU si hay CUDA, si no CPU) \| cpu \| cuda. |
| `compute_type` | texto | `default` | Precisión de CTranslate2: default \| int8 \| float16 \| int8_float16. |
| `beam_size` | entero | `1` | Beam search; 1 = más rápido, 5 = algo mejor y más lento. |
| `vad` | [VadConfig](#vadconfig) | (sección) | Segmentación por energía. |
| `max_inflight` | entero | `1` | Segmentos en paralelo por sala (la GPU es el límite). |

## TranslatorConfig

Traductor de texto usado por gemini-live, gemini-chunked (destinos extra) y local.

| Clave | Tipo | Default | Descripción |
|---|---|---|---|
| `provider` | `gemini` \| `ollama` \| `mock` \| `none` | `gemini` | gemini (nube) \| ollama (local, Gemma) \| mock (pruebas) \| none (solo transcribir). |
| `model` | texto | `gemini-3.5-flash-lite` | Modelo: gemini-3.5-flash-lite, o para Ollama gemma4:e4b / gemma4:12b. |
| `ollama_url` | texto | `http://localhost:11434` | URL del servidor Ollama. |
| `context_size` | entero | `6` | Frases previas que se pasan como contexto (más = mejor coherencia, más tokens). |
| `max_concurrency` | entero | `16` | Traducciones simultáneas en todo el proceso (protege la cuota con muchas salas). |
| `timeout_s` | número | `20.0` | Timeout por traducción. |
| `thinking` | `off` \| `auto` | `off` | off desactiva el razonamiento del modelo (más rápido y barato). |
| `temperature` | número | `0.2` | Creatividad del traductor; bajo = literal y estable. |

## SessionDefaults

Valores por defecto para todas las salas; cada sala puede pisarlos.

| Clave | Tipo | Default | Descripción |
|---|---|---|---|
| `engine` | texto | `gemini-live` | Motor: gemini-live \| gemini-live-translate \| gemini-chunked \| local \| mock. |
| `source_language` | texto \| null | `en` | Idioma que se habla (en, es, pt…) o auto para detectarlo por frase. |
| `target_languages` | lista de texto | `['es']` | Idiomas a los que se traduce. Un destino igual al idioma detectado se muestra sin traducir. |
| `glossary` | lista de texto | `[]` | Nombres propios, sponsors, tecnologías: se pasan como vocabulario al ASR y no se traducen. |
| `language_notes` | mapa | (ver descripción) | Instrucciones de estilo por idioma destino para el traductor. |
| `translator` | [TranslatorConfig](#translatorconfig) \| null | vacío | Traductor por defecto para las salas (si no, el `translator` global). |

## SessionConfig

Una sala.

| Clave | Tipo | Default | Descripción |
|---|---|---|---|
| `id` | texto | **obligatorio** | Identificador para las URLs: minúsculas, números, guiones (sala-a). |
| `name` | texto | `""` | Nombre visible para la audiencia. |
| `source` | texto | `browser` | Fuente de audio: browser \| rtmp://… \| srt://… \| https://…m3u8 \| pulse:default \| alsa:hw:0 \| archivo \| ffmpeg:<args>. |
| `source_args` | lista de texto | `[]` | Argumentos extra de entrada para ffmpeg. |
| `loop` | booleano | `False` | Repetir archivos en bucle (demos). |
| `engine` | texto \| null | vacío | Motor de esta sala (si no, defaults.engine). |
| `source_language` | texto \| null | vacío | Idioma hablado en esta sala (si no, defaults.source_language). auto = detectar. |
| `target_languages` | lista de texto \| null | vacío | Idiomas destino de esta sala (si no, defaults.target_languages). |
| `glossary` | lista de texto | `[]` | Términos adicionales a los de defaults.glossary. |
| `translator` | [TranslatorConfig](#translatorconfig) \| null | vacío | Traductor propio de esta sala (por ejemplo ollama para una sala 100 % local). |
| `autostart` | booleano | `True` | Arrancar con el servidor. false = queda creada y se inicia desde el panel. |

## Perfiles de latencia

`latency_profile` fija estos valores salvo que estén escritos a mano en el YAML:

| Perfil | gemini-live | VAD (chunked/local) | translator |
|---|---|---|---|
| `fast` | end_sensitivity=high, silence_duration_ms=300, final_chunk_timeout_s=0.8, final_chunk_max_wait_s=2.5 | min_silence_ms=400, max_segment_s=5.0 | context_size=3 |
| `balanced` | valores por defecto | valores por defecto | valores por defecto |
| `quality` | end_sensitivity=low, silence_duration_ms=800, final_chunk_timeout_s=2.0, final_chunk_max_wait_s=5.0 | min_silence_ms=800, max_segment_s=10.0 | context_size=8 |
