from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

SESSION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

DEFAULT_LANGUAGE_NOTES = {
    "es": (
        "Español neutro latinoamericano (usar 'ustedes', nunca 'vosotros'). "
        "Registro técnico pero natural, como lo diría un intérprete profesional."
    ),
    "pt": "Português brasileiro, registro técnico natural.",
    "en": "Natural, concise technical English.",
}

ENGINE_NAMES = ("gemini-live", "gemini-live-translate", "gemini-chunked", "local", "mock")
LatencyProfile = Literal["fast", "balanced", "quality"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ServerConfig(StrictModel):
    title: str = Field("Subtítulos en vivo", description="Title the audience sees on the home page.")
    host: str = Field("0.0.0.0", description="Interface the server listens on. 0.0.0.0 = all.")
    port: int = Field(8000, description="HTTP/WebSocket port.")
    admin_token: str = Field(
        "", description="Token for the panel, the admin API and the ingest. Empty = no authentication (local tests only)."
    )
    public_url: str = Field(
        "",
        description="Public URL (https://subs.myevent.org) used in QR codes and the banner. Empty = the URL each client uses.",
    )
    data_dir: str = Field("data", description="Persistence directory: JSONL transcripts per room and rooms created from the panel.")
    cors_origins: list[str] = Field(["*"], description="Allowed CORS origins (when another site consumes the API).")
    history_size: int = Field(200, description="Recent captions a viewer receives on connect.")


class VadConfig(StrictModel):
    frame_ms: int = Field(30, description="Analysis window size in ms.")
    min_silence_ms: int = Field(600, description="Silence needed to close a sentence. Less = shorter, quicker sentences.")
    min_segment_s: float = Field(1.0, description="Minimum segment length before closing it on silence.")
    max_segment_s: float = Field(8.0, description="Maximum length; when reached, the cut happens at the last detected pause.")
    pre_roll_ms: int = Field(240, description="Audio before speech onset included so the first syllable is not cut.")
    speech_threshold_db: float = Field(10.0, description="dB above the adaptive noise floor to count as speech.")
    min_speech_dbfs: float = Field(-55.0, description="Absolute minimum level (dBFS) to count as speech.")
    min_speech_ms: int = Field(300, description="Segments with less speech than this are discarded (noises, short applause).")


class GeminiConfig(StrictModel):
    api_key: str = Field("", description="Google AI Studio API key. Empty = use GEMINI_API_KEY or GOOGLE_API_KEY from the environment.")
    vertexai: bool = Field(False, description="Use Vertex AI (Google Cloud credentials) instead of an API key.")
    project: str = Field("", description="Google Cloud project (Vertex AI only).")
    location: str = Field("", description="Vertex AI region, for example us-central1.")

    def resolve_api_key(self) -> str | None:
        return self.api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or None


class LiveSessionConfig(StrictModel):
    rotate_after_s: float = Field(540.0, description="From this point on, wait for a pause of the speaker to open a new session.")
    rotate_deadline_s: float = Field(580.0, description="Rotate no matter what when this is reached, even mid-sentence.")
    rotate_quiet_ms: int = Field(400, description="How much silence counts as a pause for rotating.")
    drain_timeout_s: float = Field(3.0, description="Maximum wait for the last finals when rotating or stopping.")
    idle_close_s: float = Field(
        30.0, description="Without audio for this long the Live session is closed; it reopens by itself when audio returns."
    )
    reconnect_backoff_s: float = Field(1.0, description="Initial wait before reconnecting after an error.")
    reconnect_backoff_max_s: float = Field(20.0, description="Maximum wait between retries (grows exponentially).")


class GeminiLiveConfig(LiveSessionConfig):
    asr_model: str = Field("gemini-3.5-transcribe-live", description="Streaming transcription model of the Live API.")
    mode: Literal["VERBATIM", "SMART"] = Field(
        "SMART", description="SMART = punctuation and no fillers (best for subtitles); VERBATIM = literal."
    )
    emit_partials: bool = Field(
        True, description="Show interim hypotheses while the speaker talks (sub-second latency in the original language)."
    )
    start_sensitivity: Literal["default", "high", "low"] = Field("default", description="Speech-onset sensitivity of the model's VAD.")
    end_sensitivity: Literal["default", "high", "low"] = Field(
        "default", description="End-of-speech sensitivity: high closes sentences earlier (faster, shorter)."
    )
    silence_duration_ms: int | None = Field(None, description="Silence the model takes as end of sentence. Empty = model default.")
    prefix_padding_ms: int | None = Field(None, description="Audio before speech onset the model keeps. Empty = model default.")
    final_chunk_timeout_s: float = Field(
        1.5, description="Finals arrive in pieces: when a piece ends a sentence, it is committed after this wait without news."
    )
    final_chunk_max_wait_s: float = Field(
        4.0, description="When a piece stopped mid-sentence, wait up to this for the rest before committing."
    )


class GeminiLiveTranslateConfig(LiveSessionConfig):
    model: str = Field("gemini-3.5-live-translate-preview", description="Live translation model of the Live API.")
    echo_target_language: bool = Field(
        True, description="If the speaker already speaks the target language, pass speech/text through untranslated."
    )
    stream_audio: bool = Field(
        True, description="Rebroadcast the translated audio (24 kHz PCM) on /ws/audio/<room> so it can be heard in the viewer."
    )


class GeminiChunkedConfig(StrictModel):
    model: str = Field("gemini-3.5-flash-lite", description="Multimodal model that receives the audio.")
    vad: VadConfig = Field(default_factory=VadConfig, description="Energy-based segmentation.")
    max_inflight: int = Field(2, description="Segments processed in parallel per room.")
    timeout_s: float = Field(20.0, description="Timeout per call.")


class LocalConfig(StrictModel):
    whisper_model: str = Field(
        "small", description="Whisper size: tiny | base | small | medium | large-v3 | large-v3-turbo | distil-large-v3."
    )
    device: str = Field("auto", description="auto (GPU when CUDA is available, else CPU) | cpu | cuda.")
    compute_type: str = Field("default", description="CTranslate2 precision: default | int8 | float16 | int8_float16.")
    beam_size: int = Field(1, description="Beam search; 1 = fastest, 5 = slightly better and slower.")
    vad: VadConfig = Field(default_factory=VadConfig, description="Energy-based segmentation.")
    max_inflight: int = Field(1, description="Segments in parallel per room (the GPU is the limit).")


class TranslatorConfig(StrictModel):
    provider: Literal["gemini", "ollama", "mock", "none"] = Field(
        "gemini", description="gemini (cloud) | ollama (local, Gemma) | mock (tests) | none (transcribe only)."
    )
    model: str = Field("gemini-3.5-flash-lite", description="Model: gemini-3.5-flash-lite, or for Ollama gemma4:e4b / gemma4:12b.")
    ollama_url: str = Field("http://localhost:11434", description="URL of the Ollama server.")
    context_size: int = Field(6, description="Previous sentences passed as context (more = better coherence, more tokens).")
    max_concurrency: int = Field(16, description="Simultaneous translations in the whole process (protects the quota with many rooms).")
    timeout_s: float = Field(20.0, description="Timeout per translation.")
    thinking: Literal["off", "auto"] = Field("off", description="off disables the model's reasoning (faster and cheaper).")
    temperature: float = Field(0.2, description="Translator creativity; low = literal and stable.")


class EnginesConfig(StrictModel):
    gemini_live: GeminiLiveConfig = Field(
        default_factory=GeminiLiveConfig, alias="gemini-live", description="Settings of the gemini-live engine."
    )
    gemini_live_translate: GeminiLiveTranslateConfig = Field(
        default_factory=GeminiLiveTranslateConfig,
        alias="gemini-live-translate",
        description="Settings of the gemini-live-translate engine.",
    )
    gemini_chunked: GeminiChunkedConfig = Field(
        default_factory=GeminiChunkedConfig, alias="gemini-chunked", description="Settings of the gemini-chunked engine."
    )
    local: LocalConfig = Field(default_factory=LocalConfig, description="Settings of the local engine.")


class SessionDefaults(StrictModel):
    engine: str = Field("gemini-live", description="Engine: " + " | ".join(ENGINE_NAMES) + ".")
    source_language: str | None = Field("en", description="Language spoken (en, es, pt…) or auto to detect it per sentence.")
    target_languages: list[str] = Field(
        ["es"], description="Languages to translate into. A target equal to the detected language is shown untranslated."
    )
    glossary: list[str] = Field(
        [], description="Proper names, sponsors, technologies: passed as vocabulary to the ASR and never translated."
    )
    language_notes: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_LANGUAGE_NOTES), description="Style instructions per target language for the translator."
    )
    translator: TranslatorConfig | None = Field(None, description="Default translator for the rooms (otherwise the global `translator`).")


class SessionConfig(StrictModel):
    id: str = Field(..., description="Identifier used in URLs: lowercase letters, digits, hyphens (room-a).")
    name: str = Field("", description="Name shown to the audience.")
    source: str = Field(
        "browser",
        description="Audio source: browser | rtmp://… | srt://… | https://…m3u8 | pulse:default | alsa:hw:0 | file | ffmpeg:<args>.",
    )
    source_args: list[str] = Field([], description="Extra ffmpeg input arguments.")
    loop: bool = Field(False, description="Loop files (demos).")
    engine: str | None = Field(None, description="Engine of this room (otherwise defaults.engine).")
    source_language: str | None = Field(
        None, description="Language spoken in this room (otherwise defaults.source_language). auto = detect."
    )
    target_languages: list[str] | None = Field(None, description="Target languages of this room (otherwise defaults.target_languages).")
    glossary: list[str] = Field([], description="Terms added to defaults.glossary.")
    translator: TranslatorConfig | None = Field(None, description="Translator of this room (for example ollama for a fully local room).")
    autostart: bool = Field(True, description="Start with the server. false = created but started from the panel.")

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        if not SESSION_ID_RE.match(v):
            raise ValueError("session id must match ^[a-z0-9][a-z0-9_-]{0,63}$")
        return v

    @field_validator("engine")
    @classmethod
    def _valid_engine(cls, v: str | None) -> str | None:
        if v is not None and v not in ENGINE_NAMES:
            raise ValueError(f"unknown engine {v!r}; valid: {', '.join(ENGINE_NAMES)}")
        return v


LATENCY_PROFILES: dict[str, dict[str, dict[str, Any]]] = {
    "fast": {
        "gemini_live": {"end_sensitivity": "high", "silence_duration_ms": 300, "final_chunk_timeout_s": 0.8, "final_chunk_max_wait_s": 2.5},
        "vad": {"min_silence_ms": 400, "max_segment_s": 5.0},
        "translator": {"context_size": 3},
    },
    "balanced": {},
    "quality": {
        "gemini_live": {"end_sensitivity": "low", "silence_duration_ms": 800, "final_chunk_timeout_s": 2.0, "final_chunk_max_wait_s": 5.0},
        "vad": {"min_silence_ms": 800, "max_segment_s": 10.0},
        "translator": {"context_size": 8},
    },
}


class AppConfig(StrictModel):
    latency_profile: LatencyProfile = Field(
        "balanced",
        description="fast = short, quick sentences; balanced = middle ground; quality = complete sentences, better translation. Sets the latency parameters that are not fixed by hand (docs/LATENCY.md).",
    )
    server: ServerConfig = Field(default_factory=ServerConfig, description="Web server.")
    gemini: GeminiConfig = Field(default_factory=GeminiConfig, description="Gemini credentials.")
    engines: EnginesConfig = Field(default_factory=EnginesConfig, description="Per-engine settings.")
    translator: TranslatorConfig = Field(default_factory=TranslatorConfig, description="Global text translator.")
    defaults: SessionDefaults = Field(default_factory=SessionDefaults, description="Default values for the rooms.")
    sessions: list[SessionConfig] = Field(
        [], description="Rooms. They can also be created live from the panel (persisted to data_dir/sessions.json)."
    )

    def engine_for(self, s: SessionConfig) -> str:
        return s.engine or self.defaults.engine

    def source_language_for(self, s: SessionConfig) -> str | None:
        lang = s.source_language if s.source_language is not None else self.defaults.source_language
        return None if lang in ("", "auto") else lang

    def target_languages_for(self, s: SessionConfig) -> list[str]:
        return list(s.target_languages if s.target_languages is not None else self.defaults.target_languages)

    def glossary_for(self, s: SessionConfig) -> list[str]:
        seen: dict[str, None] = {}
        for term in [*self.defaults.glossary, *s.glossary]:
            seen.setdefault(term.strip(), None)
        return [t for t in seen if t]

    def translator_for(self, s: SessionConfig) -> TranslatorConfig:
        return s.translator or self.defaults.translator or self.translator


_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    return value


def apply_latency_profile(cfg: AppConfig, force: bool = False) -> AppConfig:
    preset = LATENCY_PROFILES[cfg.latency_profile]

    def apply(model: BaseModel, values: dict[str, Any]) -> None:
        for k, v in values.items():
            if force or k not in model.model_fields_set:
                setattr(model, k, v)

    apply(cfg.engines.gemini_live, preset.get("gemini_live", {}))
    for vad in (cfg.engines.gemini_chunked.vad, cfg.engines.local.vad):
        apply(vad, preset.get("vad", {}))
    apply(cfg.translator, preset.get("translator", {}))
    for s in cfg.sessions:
        if s.translator is not None:
            apply(s.translator, preset.get("translator", {}))
    return cfg


def load_config(path: str | os.PathLike[str] | None) -> AppConfig:
    if path is None:
        return AppConfig()
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return apply_latency_profile(AppConfig.model_validate(expand_env(raw)))
