# Configuration reference

🇦🇷 [Versión en español](es/CONFIGURACION.md)

> Generated from `transcriba/config.py` by `python scripts/gen_config_reference.py`. Do not edit by hand.

The file is YAML. Unknown keys are errors (so a typo cannot slip through). `${VAR}` and `${VAR:-default}` are replaced with environment variables; the `.env` file next to the YAML is loaded automatically.

Keys under `engines` accept hyphens or underscores (`gemini-live` or `gemini_live`).

Minimal example:

```yaml
gemini: { api_key: ${GEMINI_API_KEY} }
server: { admin_token: ${TRANSCRIBA_ADMIN_TOKEN} }
defaults: { source_language: en, target_languages: [es] }
sessions:
  - { id: room-a, name: "Room A", source: browser }
```


## AppConfig

Root of the configuration file.

| Key | Type | Default | Description |
|---|---|---|---|
| `latency_profile` | `fast` \| `balanced` \| `quality` | `balanced` | fast = short, quick sentences; balanced = middle ground; quality = complete sentences, better translation. Sets the latency parameters that are not fixed by hand (docs/LATENCY.md). |
| `server` | [ServerConfig](#serverconfig) | (section) | Web server. |
| `gemini` | [GeminiConfig](#geminiconfig) | (section) | Gemini credentials. |
| `engines` | [EnginesConfig](#enginesconfig) | (section) | Per-engine settings. |
| `translator` | [TranslatorConfig](#translatorconfig) | (section) | Global text translator. |
| `defaults` | [SessionDefaults](#sessiondefaults) | (section) | Default values for the rooms. |
| `sessions` | list of [SessionConfig](#sessionconfig) | `[]` | Rooms. They can also be created live from the panel (persisted to data_dir/sessions.json). |

## ServerConfig

Web server: ports, authentication, persistence.

| Key | Type | Default | Description |
|---|---|---|---|
| `title` | text | `Subtítulos en vivo` | Title the audience sees on the home page. |
| `host` | text | `0.0.0.0` | Interface the server listens on. 0.0.0.0 = all. |
| `port` | integer | `8000` | HTTP/WebSocket port. |
| `admin_token` | text | `""` | Token for the panel, the admin API and the ingest. Empty = no authentication (local tests only). |
| `public_url` | text | `""` | Public URL (https://subs.myevent.org) used in QR codes and the banner. Empty = the URL each client uses. |
| `data_dir` | text | `data` | Persistence directory: JSONL transcripts per room and rooms created from the panel. |
| `cors_origins` | list of text | `['*']` | Allowed CORS origins (when another site consumes the API). |
| `history_size` | integer | `200` | Recent captions a viewer receives on connect. |

## GeminiConfig

Gemini credentials (AI Studio API key or Vertex AI).

| Key | Type | Default | Description |
|---|---|---|---|
| `api_key` | text | `""` | Google AI Studio API key. Empty = use GEMINI_API_KEY or GOOGLE_API_KEY from the environment. |
| `vertexai` | boolean | `False` | Use Vertex AI (Google Cloud credentials) instead of an API key. |
| `project` | text | `""` | Google Cloud project (Vertex AI only). |
| `location` | text | `""` | Vertex AI region, for example us-central1. |

## EnginesConfig

Settings of each engine. Only the one in use needs touching.

| Key | Type | Default | Description |
|---|---|---|---|
| `gemini-live` | [GeminiLiveConfig](#geminiliveconfig) | (section) | Settings of the gemini-live engine. |
| `gemini-live-translate` | [GeminiLiveTranslateConfig](#geminilivetranslateconfig) | (section) | Settings of the gemini-live-translate engine. |
| `gemini-chunked` | [GeminiChunkedConfig](#geminichunkedconfig) | (section) | Settings of the gemini-chunked engine. |
| `local` | [LocalConfig](#localconfig) | (section) | Settings of the local engine. |

## GeminiLiveConfig

`gemini-live` engine: streaming transcription + text translator. Inherits the Live session lifecycle (rotation, drain, idle).

| Key | Type | Default | Description |
|---|---|---|---|
| `rotate_after_s` | number | `540.0` | From this point on, wait for a pause of the speaker to open a new session. |
| `rotate_deadline_s` | number | `580.0` | Rotate no matter what when this is reached, even mid-sentence. |
| `rotate_quiet_ms` | integer | `400` | How much silence counts as a pause for rotating. |
| `drain_timeout_s` | number | `3.0` | Maximum wait for the last finals when rotating or stopping. |
| `idle_close_s` | number | `30.0` | Without audio for this long the Live session is closed; it reopens by itself when audio returns. |
| `reconnect_backoff_s` | number | `1.0` | Initial wait before reconnecting after an error. |
| `reconnect_backoff_max_s` | number | `20.0` | Maximum wait between retries (grows exponentially). |
| `asr_model` | text | `gemini-3.5-transcribe-live` | Streaming transcription model of the Live API. |
| `mode` | `VERBATIM` \| `SMART` | `SMART` | SMART = punctuation and no fillers (best for subtitles); VERBATIM = literal. |
| `emit_partials` | boolean | `True` | Show interim hypotheses while the speaker talks (sub-second latency in the original language). |
| `start_sensitivity` | `default` \| `high` \| `low` | `default` | Speech-onset sensitivity of the model's VAD. |
| `end_sensitivity` | `default` \| `high` \| `low` | `default` | End-of-speech sensitivity: high closes sentences earlier (faster, shorter). |
| `silence_duration_ms` | integer \| null | empty | Silence the model takes as end of sentence. Empty = model default. |
| `prefix_padding_ms` | integer \| null | empty | Audio before speech onset the model keeps. Empty = model default. |
| `final_chunk_timeout_s` | number | `1.5` | Finals arrive in pieces: when a piece ends a sentence, it is committed after this wait without news. |
| `final_chunk_max_wait_s` | number | `4.0` | When a piece stopped mid-sentence, wait up to this for the rest before committing. |

## GeminiLiveTranslateConfig

`gemini-live-translate` engine: a single model, speech → translated speech + transcripts.

| Key | Type | Default | Description |
|---|---|---|---|
| `rotate_after_s` | number | `540.0` | From this point on, wait for a pause of the speaker to open a new session. |
| `rotate_deadline_s` | number | `580.0` | Rotate no matter what when this is reached, even mid-sentence. |
| `rotate_quiet_ms` | integer | `400` | How much silence counts as a pause for rotating. |
| `drain_timeout_s` | number | `3.0` | Maximum wait for the last finals when rotating or stopping. |
| `idle_close_s` | number | `30.0` | Without audio for this long the Live session is closed; it reopens by itself when audio returns. |
| `reconnect_backoff_s` | number | `1.0` | Initial wait before reconnecting after an error. |
| `reconnect_backoff_max_s` | number | `20.0` | Maximum wait between retries (grows exponentially). |
| `model` | text | `gemini-3.5-live-translate-preview` | Live translation model of the Live API. |
| `echo_target_language` | boolean | `True` | If the speaker already speaks the target language, pass speech/text through untranslated. |
| `stream_audio` | boolean | `True` | Rebroadcast the translated audio (24 kHz PCM) on /ws/audio/<room> so it can be heard in the viewer. |

## GeminiChunkedConfig

`gemini-chunked` engine: WAV segments → generate_content (transcribes and translates in one call).

| Key | Type | Default | Description |
|---|---|---|---|
| `model` | text | `gemini-3.5-flash-lite` | Multimodal model that receives the audio. |
| `vad` | [VadConfig](#vadconfig) | (section) | Energy-based segmentation. |
| `max_inflight` | integer | `2` | Segments processed in parallel per room. |
| `timeout_s` | number | `20.0` | Timeout per call. |

## VadConfig

Energy-based voice activity detector used by the segment-based engines (gemini-chunked, local, mock).

| Key | Type | Default | Description |
|---|---|---|---|
| `frame_ms` | integer | `30` | Analysis window size in ms. |
| `min_silence_ms` | integer | `600` | Silence needed to close a sentence. Less = shorter, quicker sentences. |
| `min_segment_s` | number | `1.0` | Minimum segment length before closing it on silence. |
| `max_segment_s` | number | `8.0` | Maximum length; when reached, the cut happens at the last detected pause. |
| `pre_roll_ms` | integer | `240` | Audio before speech onset included so the first syllable is not cut. |
| `speech_threshold_db` | number | `10.0` | dB above the adaptive noise floor to count as speech. |
| `min_speech_dbfs` | number | `-55.0` | Absolute minimum level (dBFS) to count as speech. |
| `min_speech_ms` | integer | `300` | Segments with less speech than this are discarded (noises, short applause). |

## LocalConfig

`local` engine: faster-whisper for transcription + Ollama (Gemma) for translation.

| Key | Type | Default | Description |
|---|---|---|---|
| `whisper_model` | text | `small` | Whisper size: tiny \| base \| small \| medium \| large-v3 \| large-v3-turbo \| distil-large-v3. |
| `device` | text | `auto` | auto (GPU when CUDA is available, else CPU) \| cpu \| cuda. |
| `compute_type` | text | `default` | CTranslate2 precision: default \| int8 \| float16 \| int8_float16. |
| `beam_size` | integer | `1` | Beam search; 1 = fastest, 5 = slightly better and slower. |
| `vad` | [VadConfig](#vadconfig) | (section) | Energy-based segmentation. |
| `max_inflight` | integer | `1` | Segments in parallel per room (the GPU is the limit). |

## TranslatorConfig

Text translator used by gemini-live, gemini-chunked (extra targets) and local.

| Key | Type | Default | Description |
|---|---|---|---|
| `provider` | `gemini` \| `ollama` \| `mock` \| `none` | `gemini` | gemini (cloud) \| ollama (local, Gemma) \| mock (tests) \| none (transcribe only). |
| `model` | text | `gemini-3.5-flash-lite` | Model: gemini-3.5-flash-lite, or for Ollama gemma4:e4b / gemma4:12b. |
| `ollama_url` | text | `http://localhost:11434` | URL of the Ollama server. |
| `context_size` | integer | `6` | Previous sentences passed as context (more = better coherence, more tokens). |
| `max_concurrency` | integer | `16` | Simultaneous translations in the whole process (protects the quota with many rooms). |
| `timeout_s` | number | `20.0` | Timeout per translation. |
| `thinking` | `off` \| `auto` | `off` | off disables the model's reasoning (faster and cheaper). |
| `temperature` | number | `0.2` | Translator creativity; low = literal and stable. |

## SessionDefaults

Defaults for every room; each room can override them.

| Key | Type | Default | Description |
|---|---|---|---|
| `engine` | text | `gemini-live` | Engine: gemini-live \| gemini-live-translate \| gemini-chunked \| local \| mock. |
| `source_language` | text \| null | `en` | Language spoken (en, es, pt…) or auto to detect it per sentence. |
| `target_languages` | list of text | `['es']` | Languages to translate into. A target equal to the detected language is shown untranslated. |
| `glossary` | list of text | `[]` | Proper names, sponsors, technologies: passed as vocabulary to the ASR and never translated. |
| `language_notes` | map | (see description) | Style instructions per target language for the translator. |
| `translator` | [TranslatorConfig](#translatorconfig) \| null | empty | Default translator for the rooms (otherwise the global `translator`). |

## SessionConfig

One room.

| Key | Type | Default | Description |
|---|---|---|---|
| `id` | text | **required** | Identifier used in URLs: lowercase letters, digits, hyphens (room-a). |
| `name` | text | `""` | Name shown to the audience. |
| `source` | text | `browser` | Audio source: browser \| rtmp://… \| srt://… \| https://…m3u8 \| pulse:default \| alsa:hw:0 \| file \| ffmpeg:<args>. |
| `source_args` | list of text | `[]` | Extra ffmpeg input arguments. |
| `loop` | boolean | `False` | Loop files (demos). |
| `engine` | text \| null | empty | Engine of this room (otherwise defaults.engine). |
| `source_language` | text \| null | empty | Language spoken in this room (otherwise defaults.source_language). auto = detect. |
| `target_languages` | list of text \| null | empty | Target languages of this room (otherwise defaults.target_languages). |
| `glossary` | list of text | `[]` | Terms added to defaults.glossary. |
| `translator` | [TranslatorConfig](#translatorconfig) \| null | empty | Translator of this room (for example ollama for a fully local room). |
| `autostart` | boolean | `True` | Start with the server. false = created but started from the panel. |

## Latency profiles

`latency_profile` sets these values unless they are written by hand in the YAML:

| Profile | gemini-live | VAD (chunked/local) | translator |
|---|---|---|---|
| `fast` | end_sensitivity=high, silence_duration_ms=300, final_chunk_timeout_s=0.8, final_chunk_max_wait_s=2.5 | min_silence_ms=400, max_segment_s=5.0 | context_size=3 |
| `balanced` | default values | default values | default values |
| `quality` | end_sensitivity=low, silence_duration_ms=800, final_chunk_timeout_s=2.0, final_chunk_max_wait_s=5.0 | min_silence_ms=800, max_segment_s=10.0 | context_size=8 |
