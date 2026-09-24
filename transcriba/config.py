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
    title: str = Field("Subtítulos en vivo", description="Título que ve la audiencia en la página principal.")
    host: str = Field("0.0.0.0", description="Interfaz donde escucha el servidor. 0.0.0.0 = todas.")
    port: int = Field(8000, description="Puerto HTTP/WebSocket.")
    admin_token: str = Field(
        "", description="Token para el panel, la API de administración y la ingesta. Vacío = sin autenticación (solo para pruebas locales)."
    )
    public_url: str = Field(
        "",
        description="URL pública (https://subs.mievento.org) usada en los QR y en el banner. Vacío = la URL con la que entra cada cliente.",
    )
    data_dir: str = Field(
        "data", description="Directorio de persistencia: transcripciones JSONL por sala y sesiones creadas desde el panel."
    )
    cors_origins: list[str] = Field(["*"], description="Orígenes permitidos para CORS (si otro sitio consume la API).")
    history_size: int = Field(200, description="Subtítulos recientes que recibe un visor al conectarse.")


class VadConfig(StrictModel):
    frame_ms: int = Field(30, description="Tamaño de la ventana de análisis en ms.")
    min_silence_ms: int = Field(600, description="Silencio necesario para cerrar una frase. Menos = frases más cortas y rápidas.")
    min_segment_s: float = Field(1.0, description="Duración mínima de un segmento antes de cerrarlo por silencio.")
    max_segment_s: float = Field(8.0, description="Duración máxima; al llegar se corta en la última pausa detectada.")
    pre_roll_ms: int = Field(240, description="Audio previo al inicio de voz que se incluye para no cortar la primera sílaba.")
    speech_threshold_db: float = Field(10.0, description="dB por encima del piso de ruido adaptativo para considerar voz.")
    min_speech_dbfs: float = Field(-55.0, description="Nivel absoluto mínimo (dBFS) para considerar voz.")
    min_speech_ms: int = Field(300, description="Segmentos con menos voz que esto se descartan (ruidos, aplausos cortos).")


class GeminiConfig(StrictModel):
    api_key: str = Field("", description="API key de Google AI Studio. Vacío = usar GEMINI_API_KEY o GOOGLE_API_KEY del entorno.")
    vertexai: bool = Field(False, description="Usar Vertex AI (credenciales de Google Cloud) en lugar de API key.")
    project: str = Field("", description="Proyecto de Google Cloud (solo Vertex AI).")
    location: str = Field("", description="Región de Vertex AI, por ejemplo us-central1.")

    def resolve_api_key(self) -> str | None:
        return self.api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or None


class LiveSessionConfig(StrictModel):
    rotate_after_s: float = Field(540.0, description="Desde este momento se busca una pausa del orador para abrir una sesión nueva.")
    rotate_deadline_s: float = Field(580.0, description="Se rota sí o sí al llegar aquí, aunque el orador siga hablando.")
    rotate_quiet_ms: int = Field(400, description="Cuánto silencio cuenta como pausa para rotar.")
    drain_timeout_s: float = Field(3.0, description="Espera máxima de los últimos finales al rotar o detener.")
    idle_close_s: float = Field(
        30.0, description="Sin audio durante este tiempo se cierra la sesión Live; se reabre sola al volver el audio."
    )
    reconnect_backoff_s: float = Field(1.0, description="Espera inicial antes de reconectar tras un error.")
    reconnect_backoff_max_s: float = Field(20.0, description="Espera máxima entre reintentos (crece exponencialmente).")


class GeminiLiveConfig(LiveSessionConfig):
    asr_model: str = Field("gemini-3.5-transcribe-live", description="Modelo de transcripción en streaming del Live API.")
    mode: Literal["VERBATIM", "SMART"] = Field(
        "SMART", description="SMART = puntuación y sin muletillas (mejor para subtítulos); VERBATIM = literal."
    )
    emit_partials: bool = Field(
        True, description="Mostrar hipótesis parciales mientras el orador habla (latencia sub-segundo en el idioma original)."
    )
    start_sensitivity: Literal["default", "high", "low"] = Field(
        "default", description="Sensibilidad del inicio de voz del VAD del modelo."
    )
    end_sensitivity: Literal["default", "high", "low"] = Field(
        "default", description="Sensibilidad del fin de voz: high cierra frases antes (más rápido, más cortas)."
    )
    silence_duration_ms: int | None = Field(None, description="Silencio que el modelo considera fin de frase. Vacío = valor del modelo.")
    prefix_padding_ms: int | None = Field(
        None, description="Audio previo que el modelo conserva al detectar inicio de voz. Vacío = valor del modelo."
    )
    final_chunk_timeout_s: float = Field(
        1.5, description="Los finales llegan en trozos: si el trozo termina una oración, se confirma tras esta espera sin novedades."
    )
    final_chunk_max_wait_s: float = Field(
        4.0, description="Si el trozo quedó a mitad de oración, se espera hasta esto por el resto antes de confirmar."
    )


class GeminiLiveTranslateConfig(LiveSessionConfig):
    model: str = Field("gemini-3.5-live-translate-preview", description="Modelo de traducción en vivo del Live API.")
    echo_target_language: bool = Field(True, description="Si el orador ya habla en el idioma destino, pasar su voz/texto sin traducir.")
    stream_audio: bool = Field(
        True, description="Retransmitir el audio traducido (PCM 24 kHz) por /ws/audio/<sala> para escucharlo en el visor."
    )


class GeminiChunkedConfig(StrictModel):
    model: str = Field("gemini-3.5-flash-lite", description="Modelo multimodal que recibe el audio.")
    vad: VadConfig = Field(default_factory=VadConfig, description="Segmentación por energía.")
    max_inflight: int = Field(2, description="Segmentos procesándose en paralelo por sala.")
    timeout_s: float = Field(20.0, description="Timeout por llamada.")


class LocalConfig(StrictModel):
    whisper_model: str = Field(
        "small", description="Tamaño de Whisper: tiny | base | small | medium | large-v3 | large-v3-turbo | distil-large-v3."
    )
    device: str = Field("auto", description="auto (GPU si hay CUDA, si no CPU) | cpu | cuda.")
    compute_type: str = Field("default", description="Precisión de CTranslate2: default | int8 | float16 | int8_float16.")
    beam_size: int = Field(1, description="Beam search; 1 = más rápido, 5 = algo mejor y más lento.")
    vad: VadConfig = Field(default_factory=VadConfig, description="Segmentación por energía.")
    max_inflight: int = Field(1, description="Segmentos en paralelo por sala (la GPU es el límite).")


class TranslatorConfig(StrictModel):
    provider: Literal["gemini", "ollama", "mock", "none"] = Field(
        "gemini", description="gemini (nube) | ollama (local, Gemma) | mock (pruebas) | none (solo transcribir)."
    )
    model: str = Field("gemini-3.5-flash-lite", description="Modelo: gemini-3.5-flash-lite, o para Ollama gemma4:e4b / gemma4:12b.")
    ollama_url: str = Field("http://localhost:11434", description="URL del servidor Ollama.")
    context_size: int = Field(6, description="Frases previas que se pasan como contexto (más = mejor coherencia, más tokens).")
    max_concurrency: int = Field(16, description="Traducciones simultáneas en todo el proceso (protege la cuota con muchas salas).")
    timeout_s: float = Field(20.0, description="Timeout por traducción.")
    thinking: Literal["off", "auto"] = Field("off", description="off desactiva el razonamiento del modelo (más rápido y barato).")
    temperature: float = Field(0.2, description="Creatividad del traductor; bajo = literal y estable.")


class EnginesConfig(StrictModel):
    gemini_live: GeminiLiveConfig = Field(
        default_factory=GeminiLiveConfig, alias="gemini-live", description="Ajustes del motor gemini-live."
    )
    gemini_live_translate: GeminiLiveTranslateConfig = Field(
        default_factory=GeminiLiveTranslateConfig, alias="gemini-live-translate", description="Ajustes del motor gemini-live-translate."
    )
    gemini_chunked: GeminiChunkedConfig = Field(
        default_factory=GeminiChunkedConfig, alias="gemini-chunked", description="Ajustes del motor gemini-chunked."
    )
    local: LocalConfig = Field(default_factory=LocalConfig, description="Ajustes del motor local.")


class SessionDefaults(StrictModel):
    engine: str = Field("gemini-live", description="Motor: " + " | ".join(ENGINE_NAMES) + ".")
    source_language: str | None = Field("en", description="Idioma que se habla (en, es, pt…) o auto para detectarlo por frase.")
    target_languages: list[str] = Field(
        ["es"], description="Idiomas a los que se traduce. Un destino igual al idioma detectado se muestra sin traducir."
    )
    glossary: list[str] = Field(
        [], description="Nombres propios, sponsors, tecnologías: se pasan como vocabulario al ASR y no se traducen."
    )
    language_notes: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_LANGUAGE_NOTES), description="Instrucciones de estilo por idioma destino para el traductor."
    )
    translator: TranslatorConfig | None = Field(None, description="Traductor por defecto para las salas (si no, el `translator` global).")


class SessionConfig(StrictModel):
    id: str = Field(..., description="Identificador para las URLs: minúsculas, números, guiones (sala-a).")
    name: str = Field("", description="Nombre visible para la audiencia.")
    source: str = Field(
        "browser",
        description="Fuente de audio: browser | rtmp://… | srt://… | https://…m3u8 | pulse:default | alsa:hw:0 | archivo | ffmpeg:<args>.",
    )
    source_args: list[str] = Field([], description="Argumentos extra de entrada para ffmpeg.")
    loop: bool = Field(False, description="Repetir archivos en bucle (demos).")
    engine: str | None = Field(None, description="Motor de esta sala (si no, defaults.engine).")
    source_language: str | None = Field(None, description="Idioma hablado en esta sala (si no, defaults.source_language). auto = detectar.")
    target_languages: list[str] | None = Field(None, description="Idiomas destino de esta sala (si no, defaults.target_languages).")
    glossary: list[str] = Field([], description="Términos adicionales a los de defaults.glossary.")
    translator: TranslatorConfig | None = Field(
        None, description="Traductor propio de esta sala (por ejemplo ollama para una sala 100 % local)."
    )
    autostart: bool = Field(True, description="Arrancar con el servidor. false = queda creada y se inicia desde el panel.")

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
        description="fast = frases cortas y rápidas; balanced = equilibrio; quality = frases completas, mejor traducción. Ajusta los parámetros de latencia que no estén fijados a mano (docs/LATENCIA.md).",
    )
    server: ServerConfig = Field(default_factory=ServerConfig, description="Servidor web.")
    gemini: GeminiConfig = Field(default_factory=GeminiConfig, description="Credenciales de Gemini.")
    engines: EnginesConfig = Field(default_factory=EnginesConfig, description="Ajustes por motor.")
    translator: TranslatorConfig = Field(default_factory=TranslatorConfig, description="Traductor de texto global.")
    defaults: SessionDefaults = Field(default_factory=SessionDefaults, description="Valores por defecto de las salas.")
    sessions: list[SessionConfig] = Field(
        [], description="Salas. También se pueden crear en caliente desde el panel (se persisten en data_dir/sessions.json)."
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
